"""P1A analysis-completion shadow wiring with no execution capability."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from types import MappingProxyType
from typing import Any, Callable, Literal

from src.analyzer import AnalysisResult
from src.core.trading_calendar import get_market_for_stock
from src.investment.contracts.base import canonical_json_bytes, decimal_to_json
from src.investment.contracts.investment_decision import (
    EntryPlan,
    InvestmentDecision,
    StopPlan,
    TakeProfitPlan,
)
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.contracts.research_bundle import ModelProvenance, ResearchBundle
from src.investment.contracts.risk_policy import RiskPolicy
from src.investment.decision.engine import DecisionSizingInput, InvestmentDecisionEngine
from src.investment.decision.sizing import risk_budget_target_weight
from src.investment.execution_projection.decision_signal import DecisionSignalProjector
from src.investment.research.adapter import ResearchBundleAdapter
from src.investment.snapshot_timing import (
    MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW,
    portfolio_snapshot_is_future_dated,
)
from src.schemas.decision_action import normalize_decision_action
from src.services.decision_signal_data_quality import normalize_decision_signal_data_quality
from src.utils.sniper_points import extract_sniper_points


_RETURN_QUANTUM = Decimal("0.000001")
_CONFIDENCE = {
    "high": Decimal("0.800000"),
    "高": Decimal("0.800000"),
    "medium": Decimal("0.600000"),
    "mid": Decimal("0.600000"),
    "中": Decimal("0.600000"),
    "low": Decimal("0.400000"),
    "低": Decimal("0.400000"),
}
_QUALITY = {
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "poor": "UNKNOWN",
    "unknown": "UNKNOWN",
}
_ACTIONABLE_LONG_ACTIONS = frozenset({"buy", "add"})
_NON_ACTIONABLE_ACTIONS = frozenset({"watch", "hold", "avoid", "alert"})
_UNSUPPORTED_DIRECTION_ACTIONS = frozenset({"reduce", "sell"})


class ShadowWiringRejected(ValueError):
    """Raised when P1A cannot prove that its injected inputs are usable."""


@dataclass(frozen=True)
class InvestmentShadowArtifacts:
    """Internal-only lineage artifacts with no execution capability."""

    source_report_id: int
    research_bundle: ResearchBundle
    portfolio_snapshot_a: PortfolioSnapshot
    risk_policy: RiskPolicy
    investment_decision: InvestmentDecision
    decision_signal: Mapping[str, Any]
    shadow_mandate: None = None
    shadow_only: Literal[True] = True
    execution_permitted: Literal[False] = False


class InvestmentShadowWiringService:
    """Pure DSA wiring from a completed analysis to internal shadow artifacts."""

    MAX_SNAPSHOT_AGE = timedelta(minutes=5)
    # Compatibility alias; the shared authority timing module owns this budget.
    MAX_SNAPSHOT_CLOCK_SKEW = MAX_PORTFOLIO_SNAPSHOT_CLOCK_SKEW
    DECISION_VALIDITY = timedelta(minutes=5)

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build_from_analysis(
        self,
        *,
        result: AnalysisResult,
        context_snapshot: Mapping[str, Any],
        source_report_id: int,
        trace_id: str,
        trigger_source: str,
        portfolio_snapshot: PortfolioSnapshot,
        risk_policy: RiskPolicy,
        decision_cycle_id: str | None = None,
        decision_id: str | None = None,
        allow_nonpositive_return: bool = False,
    ) -> InvestmentShadowArtifacts:
        """Build one decision lineage without persistence, transport, or execution."""

        now = self._aware_now()
        self._validate_inputs(
            result=result,
            source_report_id=source_report_id,
            portfolio_snapshot=portfolio_snapshot,
            risk_policy=risk_policy,
            now=now,
        )

        symbol = str(result.code or "").strip()
        market = str(get_market_for_stock(symbol) or "").strip().upper()
        if market != "CN":
            raise ShadowWiringRejected("P1A shadow wiring is limited to CN equities")

        research_actionability = self._research_actionability(result)
        if research_actionability == "ACTIONABLE_LONG":
            entry_floor, entry_limit, stop_price, target_price = self._price_plan(result)
            expected_return = ((target_price - entry_limit) / entry_limit).quantize(
                _RETURN_QUANTUM,
                rounding=ROUND_DOWN,
            )
            if expected_return <= 0 and not allow_nonpositive_return:
                raise ShadowWiringRejected("completed analysis has no positive target return")
        else:
            entry_floor = entry_limit = stop_price = target_price = None
            expected_return = Decimal("0")

        effective_trace_id = str(trace_id or "").strip()
        if not effective_trace_id:
            raise ShadowWiringRejected("trace_id is required")
        source = str(trigger_source or "").strip() or "system"
        identity_hash = hashlib.sha256(
            canonical_json_bytes(
                {
                    "trace_id": effective_trace_id,
                    "source_report_id": source_report_id,
                    "symbol": symbol,
                    "portfolio_snapshot_hash": portfolio_snapshot.content_hash,
                    "risk_policy_id": risk_policy.policy_id,
                    "risk_policy_version": risk_policy.policy_version,
                }
            )
        ).hexdigest()
        effective_decision_cycle_id = (
            str(decision_cycle_id).strip()
            if decision_cycle_id is not None
            else f"decision-cycle-shadow-{identity_hash[:32]}"
        )
        effective_decision_id = (
            str(decision_id).strip()
            if decision_id is not None
            else f"decision-shadow-{identity_hash[:32]}"
        )
        if not effective_decision_cycle_id or not effective_decision_id:
            raise ShadowWiringRejected("explicit shadow decision identities cannot be blank")

        research = ResearchBundleAdapter.from_dsa_views(
            research_id=f"research-shadow-{identity_hash[:32]}",
            trace_id=effective_trace_id,
            created_at=now,
            producer="DSA_ANALYSIS_SHADOW_ADAPTER",
            symbol=symbol,
            market=market,
            as_of=now,
            horizon="swing",
            trigger_source=source,
            market_regime=self._text(
                getattr(result, "trend_prediction", None),
                "Completed DSA analysis did not provide a market-regime view.",
            ),
            industry_view=self._text(
                getattr(result, "sector_position", None),
                "Completed DSA analysis did not provide a separate industry view.",
            ),
            fundamental_view=self._text(
                getattr(result, "fundamental_analysis", None),
                "Completed DSA analysis did not provide a separate fundamental view.",
            ),
            technical_view=self._first_text(
                getattr(result, "technical_analysis", None),
                getattr(result, "trend_analysis", None),
                getattr(result, "ma_analysis", None),
                fallback="Completed DSA analysis did not provide a separate technical view.",
            ),
            valuation_view=self._text(
                self._nested_text(getattr(result, "fundamental_context", None), "valuation"),
                "Completed DSA analysis did not provide a separate valuation view.",
            ),
            intel_view=self._first_text(
                getattr(result, "news_summary", None),
                getattr(result, "market_sentiment", None),
                getattr(result, "hot_topics", None),
                fallback="Completed DSA analysis did not provide a separate intelligence view.",
            ),
            capital_flow_view=self._text(
                getattr(result, "volume_analysis", None),
                "Completed DSA analysis did not provide a separate capital-flow view.",
            ),
            bull_case=self._first_text(
                getattr(result, "company_highlights", None),
                getattr(result, "medium_term_outlook", None),
                getattr(result, "analysis_summary", None),
                fallback="Completed DSA analysis did not provide a separate bull case.",
            ),
            base_case=self._first_text(
                getattr(result, "analysis_summary", None),
                self._core_conclusion(result),
                getattr(result, "key_points", None),
                fallback="Completed DSA analysis did not provide a base case.",
            ),
            bear_case=self._text(
                getattr(result, "risk_warning", None),
                "Completed DSA analysis did not provide a separate bear case.",
            ),
            expected_return_minimum=expected_return,
            expected_return_maximum=expected_return,
            catalysts=self._unique_texts(
                getattr(result, "company_highlights", None),
                getattr(result, "hot_topics", None),
            ),
            risk_factors=self._unique_texts(
                getattr(result, "risk_warning", None),
                *self._risk_alerts(result),
            ),
            invalidation_conditions=(
                (
                    f"Observed price falls below the DSA stop plan {decimal_to_json(stop_price)}."
                    if stop_price is not None
                    else "Research is non-actionable; require a new completed analysis before entry."
                ),
            ),
            evidence_refs=(
                f"dsa-analysis-history:{source_report_id}",
                f"dsa-analysis-trace:{effective_trace_id}",
            ),
            data_quality=self._data_quality(context_snapshot, result),
            confidence=self._confidence(result),
            model_provenance=(
                ModelProvenance(
                    model_name=self._text(
                        getattr(result, "model_used", None),
                        "DSA_COMPLETED_ANALYSIS",
                    ),
                    model_version="analysis-result-v1",
                    provider="DSA",
                    prompt_hash=None,
                ),
            ),
            strategy_refs=("p1a-shadow-wiring",),
        )

        valid_until = now + self.DECISION_VALIDITY
        if risk_policy.effective_until is not None:
            policy_boundary = risk_policy.effective_until - timedelta(microseconds=1)
            valid_until = min(valid_until, policy_boundary)
        if valid_until <= now:
            raise ShadowWiringRejected("risk policy does not cover the shadow validity window")

        decision = InvestmentDecisionEngine().decide(
            research=research,
            portfolio=portfolio_snapshot,
            risk_policy=risk_policy,
            sizing=DecisionSizingInput(
                decision_id=effective_decision_id,
                decision_cycle_id=effective_decision_cycle_id,
                created_at=now,
                valid_from=now,
                valid_until=valid_until,
                proposed_target_weight=(
                    risk_budget_target_weight(
                        entry_limit=entry_limit,
                        stop_price=stop_price,
                        risk_budget_per_trade=risk_policy.risk_budget_per_trade,
                        max_single_position_weight=risk_policy.max_single_position_weight,
                    )
                    if research_actionability == "ACTIONABLE_LONG"
                    else None
                ),
                lot_size=100,
                entry_plan=(
                    EntryPlan(
                        limit_price=entry_limit,
                        price_floor=entry_floor,
                        price_ceiling=entry_limit,
                    )
                    if entry_limit is not None and entry_floor is not None
                    else None
                ),
                stop_plan=StopPlan(stop_price=stop_price) if stop_price is not None else None,
                take_profit_plan=(TakeProfitPlan(target_price=target_price) if target_price is not None else None),
                rationale=(
                    research.base_case
                    if research_actionability == "ACTIONABLE_LONG" and expected_return > 0
                    else (
                        f"HOLD: structured research is non-actionable; "
                        f"weakening evidence: {research.bear_case}"
                    )
                ),
                horizon=research.horizon,
                producer="DSA_INVESTMENT_SHADOW_DECISION_ENGINE",
                research_actionability=research_actionability,
            ),
        )
        decision_signal = DecisionSignalProjector.project(decision)
        metadata = dict(decision_signal.get("metadata") or {})
        metadata.update(
            {
                "shadow_only": True,
                "execution_permitted": False,
                "persistence_permitted": False,
                "source_report_id": source_report_id,
            }
        )
        decision_signal.update(
            {
                "shadow_only": True,
                "execution_permitted": False,
                "metadata": metadata,
            }
        )
        return InvestmentShadowArtifacts(
            source_report_id=source_report_id,
            research_bundle=research,
            portfolio_snapshot_a=portfolio_snapshot,
            risk_policy=risk_policy,
            investment_decision=decision,
            decision_signal=self._freeze(decision_signal),
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ShadowWiringRejected("shadow clock must return a timezone-aware datetime")
        return value

    def _validate_inputs(
        self,
        *,
        result: AnalysisResult,
        source_report_id: int,
        portfolio_snapshot: PortfolioSnapshot,
        risk_policy: RiskPolicy,
        now: datetime,
    ) -> None:
        if not isinstance(result, AnalysisResult) or not result.success:
            raise ShadowWiringRejected("a successful completed AnalysisResult is required")
        if not isinstance(source_report_id, int) or isinstance(source_report_id, bool) or source_report_id <= 0:
            raise ShadowWiringRejected("a persisted analysis history id is required")
        if not isinstance(portfolio_snapshot, PortfolioSnapshot):
            raise ShadowWiringRejected("an injected canonical PortfolioSnapshot is required")
        if not isinstance(risk_policy, RiskPolicy):
            raise ShadowWiringRejected("an injected canonical RiskPolicy is required")
        if portfolio_snapshot_is_future_dated(
            as_of=portfolio_snapshot.as_of,
            reference_time=now,
        ):
            raise ShadowWiringRejected("authoritative portfolio snapshot is from the future")
        if now - portfolio_snapshot.as_of > self.MAX_SNAPSHOT_AGE:
            raise ShadowWiringRejected("authoritative portfolio snapshot is stale")
        if not risk_policy.applies_to(portfolio_snapshot.account_id):
            raise ShadowWiringRejected("risk policy does not apply to the authoritative account")
        if not risk_policy.is_effective_at(now):
            raise ShadowWiringRejected("risk policy is not currently effective")

    @staticmethod
    def _price_plan(result: AnalysisResult) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        points = extract_sniper_points(result)
        entries = [
            price
            for price in (
                InvestmentShadowWiringService._decimal(points.get("ideal_buy")),
                InvestmentShadowWiringService._decimal(points.get("secondary_buy")),
            )
            if price is not None
        ]
        if not entries:
            current_price = InvestmentShadowWiringService._decimal(
                getattr(result, "current_price", None)
            )
            if current_price is not None:
                entries.append(current_price)
        stop_price = InvestmentShadowWiringService._decimal(points.get("stop_loss"))
        target_price = InvestmentShadowWiringService._decimal(points.get("take_profit"))
        if not entries or stop_price is None or target_price is None:
            raise ShadowWiringRejected("completed analysis lacks an entry, stop, or target price")
        entry_floor = min(entries)
        entry_limit = max(entries)
        if stop_price >= entry_limit:
            raise ShadowWiringRejected("completed analysis stop is not below the entry limit")
        if target_price <= entry_limit:
            raise ShadowWiringRejected("completed analysis target is not above the entry limit")
        return entry_floor, entry_limit, stop_price, target_price

    @staticmethod
    def _research_actionability(
        result: AnalysisResult,
    ) -> Literal["ACTIONABLE_LONG", "NON_ACTIONABLE"]:
        """Map only explicit canonical research states; unknown states fail closed."""

        action = normalize_decision_action(getattr(result, "action", None))
        if action in _ACTIONABLE_LONG_ACTIONS:
            return "ACTIONABLE_LONG"
        if action in _NON_ACTIONABLE_ACTIONS:
            return "NON_ACTIONABLE"
        if action in _UNSUPPORTED_DIRECTION_ACTIONS:
            raise ShadowWiringRejected(
                f"structured research action {action} is outside BUY/ADD/HOLD capability"
            )
        raise ShadowWiringRejected(
            "completed analysis action is missing, ambiguous, or unrecognized"
        )

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() and parsed > 0 else None

    @staticmethod
    def _data_quality(
        context_snapshot: Mapping[str, Any],
        result: AnalysisResult,
    ) -> str:
        quality: Any = context_snapshot
        if not quality:
            quality = getattr(result, "analysis_context_pack_overview", None)
        normalized = normalize_decision_signal_data_quality(quality)
        return _QUALITY[normalized]

    @staticmethod
    def _confidence(result: AnalysisResult) -> Decimal:
        key = str(getattr(result, "confidence_level", "") or "").strip().lower()
        return _CONFIDENCE.get(key, Decimal("0.500000"))

    @staticmethod
    def _text(value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        return text or fallback

    @staticmethod
    def _first_text(*values: Any, fallback: str) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return fallback

    @staticmethod
    def _nested_text(value: Any, key: str) -> Any:
        return value.get(key) if isinstance(value, Mapping) else None

    @staticmethod
    def _core_conclusion(result: AnalysisResult) -> str:
        getter = getattr(result, "get_core_conclusion", None)
        return str(getter() or "").strip() if callable(getter) else ""

    @staticmethod
    def _risk_alerts(result: AnalysisResult) -> tuple[str, ...]:
        getter = getattr(result, "get_risk_alerts", None)
        if not callable(getter):
            return ()
        values = getter() or ()
        return tuple(str(value).strip() for value in values if str(value).strip())

    @staticmethod
    def _unique_texts(*values: Any) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return tuple(result)

    @staticmethod
    def _freeze(value: Any) -> Any:
        if isinstance(value, Mapping):
            return MappingProxyType(
                {key: InvestmentShadowWiringService._freeze(item) for key, item in value.items()}
            )
        if isinstance(value, list):
            return tuple(InvestmentShadowWiringService._freeze(item) for item in value)
        if isinstance(value, tuple):
            return tuple(InvestmentShadowWiringService._freeze(item) for item in value)
        return value
