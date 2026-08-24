"""Durable identity bridge from Market Review context to proposal evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any, Optional

from src.storage import AnalysisHistory, DatabaseManager, MarketReviewLineageRecord, to_utc_naive_datetime


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_context(context: Mapping[str, Any]) -> tuple[str, str, str, date, str]:
    if not isinstance(context, Mapping):
        raise TypeError("market_review_context must be a mapping")
    source_task_id = str(context.get("source_task_id") or "").strip()
    market_review_id = str(context.get("market_review_id") or "").strip()
    market_context_id = str(context.get("context_id") or "").strip()
    trade_date_text = str(context.get("trade_date") or "").strip()
    as_of = _parse_timestamp(context.get("as_of"))
    provenance = context.get("provenance")
    if not source_task_id or not market_review_id or not market_context_id:
        raise ValueError("market review context identity is incomplete")
    if market_review_id != source_task_id:
        raise ValueError("market review id must match source task id")
    if not isinstance(provenance, Mapping) or provenance.get("source_task_id") != source_task_id:
        raise ValueError("market review context provenance does not preserve source task identity")
    try:
        trade_date = date.fromisoformat(trade_date_text)
    except ValueError as exc:
        raise ValueError("market review context trade_date is invalid") from exc
    if as_of is None or as_of.date() != trade_date:
        raise ValueError("market review context as_of/trade_date mismatch")
    context_hash = hashlib.sha256(_canonical(context)).hexdigest()
    return source_task_id, market_review_id, market_context_id, trade_date, context_hash


class MarketReviewLinkageConflictError(RuntimeError):
    """Raised when one immutable Market Review identity is reused with new links."""


class MarketReviewLinkageRepository:
    """Persist/read only the identity bridge; it never owns investment authority."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    @staticmethod
    def validate_context(market_review_context: Mapping[str, Any]) -> None:
        """Validate an immutable MarketContext before downstream handoff."""
        _as_context(market_review_context)

    def persist_linkage(
        self,
        *,
        market_review_context: Mapping[str, Any],
        proposal_cycle_id: str,
        candidate_count: int,
        outcome_id: str | None = None,
        research_trigger_ids: tuple[str, ...] = (),
        proposal_ids: tuple[str, ...] = (),
        acknowledgement_ids: tuple[str, ...] = (),
        linked_at: datetime | None = None,
    ) -> dict[str, Any]:
        (
            market_review_task_id,
            market_review_id,
            market_context_id,
            trade_date,
            market_context_hash,
        ) = _as_context(market_review_context)
        proposal_cycle_id = str(proposal_cycle_id or "").strip()
        if not proposal_cycle_id:
            raise ValueError("proposal_cycle_id is required")
        candidate_count = int(candidate_count)
        if candidate_count < 0:
            raise ValueError("candidate_count cannot be negative")

        def _normalize_ids(values: tuple[str, ...], field: str) -> tuple[str, ...]:
            normalized = tuple(str(value or "").strip() for value in values)
            if any(not value for value in normalized):
                raise ValueError(f"{field} cannot contain blank IDs")
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{field} cannot contain duplicate IDs")
            return normalized

        research_trigger_ids = _normalize_ids(research_trigger_ids, "research_trigger_ids")
        proposal_ids = _normalize_ids(proposal_ids, "proposal_ids")
        acknowledgement_ids = _normalize_ids(acknowledgement_ids, "acknowledgement_ids")
        outcome_id = str(outcome_id or "").strip() or None
        if candidate_count == 0:
            if not outcome_id or research_trigger_ids or proposal_ids or acknowledgement_ids:
                raise ValueError("zero-candidate linkage requires only a durable NO_ACTION outcome")
        elif (
            not research_trigger_ids
            or not proposal_ids
            or len(research_trigger_ids) != len(proposal_ids)
            or len(proposal_ids) != len(acknowledgement_ids)
            or candidate_count != len(proposal_ids)
        ):
            raise ValueError("positive linkage requires trigger, proposal and acknowledgement IDs")
        elif outcome_id is not None:
            raise ValueError("positive linkage cannot carry a NO_ACTION outcome")

        linked = linked_at or datetime.now(timezone.utc)
        if linked.tzinfo is None or linked.utcoffset() is None:
            raise ValueError("linked_at must be timezone-aware")
        linked_utc = linked.astimezone(timezone.utc)
        identity = {
            "market_review_task_id": market_review_task_id,
            "market_review_id": market_review_id,
            "market_context_id": market_context_id,
            "trade_date": trade_date.isoformat(),
            "proposal_cycle_id": proposal_cycle_id,
        }
        linkage_id = f"market-review-link-{hashlib.sha256(_canonical(identity)).hexdigest()[:32]}"
        provenance = {
            "source": "DSA.MarketReview.ProposalHandoffLoopService",
            "record_type": "canonical_market_review_lineage_linkage",
            "market_review_task_id": market_review_task_id,
            "market_context_id": market_context_id,
            "proposal_cycle_id": proposal_cycle_id,
            "integrity_method": "sha256-canonical-json-v1",
            "execution_authority": False,
            "simulation_only": True,
            "LIVE_TRADING": False,
        }
        content_body = {
            **identity,
            "candidate_count": candidate_count,
            "outcome_id": outcome_id,
            "research_trigger_ids": list(research_trigger_ids),
            "proposal_ids": list(proposal_ids),
            "acknowledgement_ids": list(acknowledgement_ids),
            "market_context_hash": market_context_hash,
            "linked_at": linked_utc.isoformat(),
            "provenance": provenance,
        }
        content_hash = hashlib.sha256(_canonical(content_body)).hexdigest()
        with self.db.session_scope() as session:
            existing = session.get(MarketReviewLineageRecord, linkage_id)
            if existing is not None:
                if existing.content_hash != content_hash:
                    raise MarketReviewLinkageConflictError(
                        f"linkage_id was reused with different content: {linkage_id}"
                    )
                return existing.to_dict()
            record = MarketReviewLineageRecord(
                linkage_id=linkage_id,
                market_review_task_id=market_review_task_id,
                market_review_id=market_review_id,
                market_context_id=market_context_id,
                trade_date=trade_date,
                proposal_cycle_id=proposal_cycle_id,
                candidate_count=candidate_count,
                outcome_id=outcome_id,
                research_trigger_ids_json=json.dumps(
                    list(research_trigger_ids), ensure_ascii=False, separators=(",", ":")
                ),
                proposal_ids_json=json.dumps(
                    list(proposal_ids), ensure_ascii=False, separators=(",", ":")
                ),
                acknowledgement_ids_json=json.dumps(
                    list(acknowledgement_ids), ensure_ascii=False, separators=(",", ":")
                ),
                market_context_hash=market_context_hash,
                linked_at=to_utc_naive_datetime(linked_utc),
                provenance_json=json.dumps(
                    provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                content_hash=content_hash,
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    def get_for_context(
        self,
        *,
        market_review_task_id: str,
        market_context_id: str,
        trade_date: date,
    ) -> dict[str, Any] | None:
        with self.db.session_scope() as session:
            rows = (
                session.query(MarketReviewLineageRecord)
                .filter(
                    MarketReviewLineageRecord.market_review_task_id == str(market_review_task_id),
                    MarketReviewLineageRecord.market_context_id == str(market_context_id),
                    MarketReviewLineageRecord.trade_date == trade_date,
                )
                .all()
            )
            if len(rows) != 1:
                return None
            return rows[0].to_dict()

    def latest_market_context(
        self,
        *,
        trade_date: date,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Resolve one explicit causal MarketContext for a cycle.

        The old resolver treated multiple same-day contexts as inherently
        ambiguous and returned ``None``.  A cycle now supplies its observation
        cutoff, so the resolver chooses the newest real context at or before
        that cutoff.  Equal-time distinct contexts remain fail-closed.
        """
        with self.db.session_scope() as session:
            snapshots = (
                session.query(AnalysisHistory.context_snapshot, AnalysisHistory.created_at)
                .filter(AnalysisHistory.report_type == "market_review")
                .order_by(AnalysisHistory.created_at.desc(), AnalysisHistory.id.desc())
                .all()
            )
        cutoff = None
        if as_of is not None:
            cutoff = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
            cutoff = cutoff.astimezone(timezone.utc)
        candidates: list[tuple[datetime, datetime, tuple[str, str], dict[str, Any], str]] = []
        for context_snapshot, created_at in snapshots:
            try:
                snapshot = json.loads(context_snapshot or "{}")
            except (TypeError, ValueError):
                continue
            payload = snapshot.get("market_review_payload") if isinstance(snapshot, dict) else None
            context = payload.get("market_context") if isinstance(payload, dict) else None
            contexts = [context] if isinstance(context, Mapping) and context.get("source_task_id") else []
            for item in contexts:
                try:
                    task_id, _, context_id, item_date, item_hash = _as_context(item)
                except (TypeError, ValueError):
                    continue
                if item_date != trade_date:
                    continue
                item_as_of = _parse_timestamp(item.get("as_of"))
                if item_as_of is None:
                    continue
                if cutoff is not None and item_as_of > cutoff:
                    continue
                created = created_at
                if created is None:
                    created = item_as_of.replace(tzinfo=None)
                elif created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                else:
                    created = created.astimezone(timezone.utc)
                candidates.append(
                    (item_as_of, created, (task_id, context_id), dict(item), item_hash)
                )
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        latest_as_of = candidates[-1][0]
        latest = [item for item in candidates if item[0] == latest_as_of]
        if len({item[2] for item in latest}) != 1:
            return None
        return dict(latest[-1][3])
