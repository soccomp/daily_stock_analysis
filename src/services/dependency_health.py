"""Persistent, read-only dependency health for the Pallas-010 runtime.

The store is deliberately separate from the investment/runtime scheduler.  It
records observations made by real callers (news providers and Codex/Luna)
and exposes a small, restart-safe snapshot for the Cockpit.  It never submits
orders, creates proposals, or changes provider configuration.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
DISABLED = "DISABLED"
HEALTH_STATUSES = frozenset({HEALTHY, DEGRADED, FAILED, STALE, UNKNOWN, DISABLED})

READINESS_READY = "READY"
READINESS_DEGRADED = "DEGRADED"
READINESS_BLOCKED = "BLOCKED"

CRITICAL_CATEGORIES = ("LLM_RESEARCH", "RESEARCH_MARKET_DATA", "MARKET_CONTEXT")
_CATEGORY_PURPOSE = {
    "LLM_RESEARCH": "structured Pallas research generation",
    "RESEARCH_MARKET_DATA": "research and screening market evidence",
    "MARKET_CONTEXT": "causal market review context",
    "NEWS_SEARCH": "advisory research news enrichment",
}

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "runtime" / "dependency_health.json"
_DEFAULT_INTERVAL_SECONDS = 300
_DEFAULT_LLM_GENERATION_TTL_SECONDS = 900
_MAX_TRANSITIONS = 300
_MAX_ALERTS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int = 240) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] if text else None


def _safe_endpoint(value: Any) -> Optional[str]:
    """Keep host/path provenance without persisting query strings or secrets."""
    text = _safe_text(value, 300)
    if not text:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(text)
        if parsed.scheme and parsed.netloc:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    except Exception:
        pass
    return text.split("?", 1)[0].split("#", 1)[0]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _failure_class(error: Any) -> Optional[str]:
    if not error:
        return None
    text = _safe_text(error, 80) or "UNKNOWN"
    return text.upper().replace(" ", "_")[:80]


def _safe_metadata(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    safe: Dict[str, Any] = {}
    for key, item in list(value.items())[:30]:
        if any(token in str(key).lower() for token in ("key", "token", "secret", "password", "prompt", "header")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[str(key)[:80]] = item
        elif isinstance(item, Mapping):
            safe[str(key)[:80]] = _safe_metadata(item)
        elif isinstance(item, (list, tuple)):
            safe[str(key)[:80]] = [str(part)[:120] for part in item[:10]]
    return safe


def _status_for_observation(
    *,
    configured: bool,
    enabled: bool,
    success: Optional[bool],
    reachable: Optional[bool],
    usable: Optional[bool],
    records: int,
    empty_valid: bool,
    data_timestamp: Optional[str],
    max_age_seconds: Optional[int],
) -> str:
    if not configured or not enabled:
        return DISABLED
    if success is None and reachable is None:
        return UNKNOWN
    if success is False or reachable is False:
        return FAILED
    if data_timestamp and max_age_seconds is not None:
        observed_at = _parse_timestamp(data_timestamp)
        if observed_at is not None and (_now() - observed_at).total_seconds() > max_age_seconds:
            return STALE
    if usable is False or (records <= 0 and not empty_valid):
        return DEGRADED
    return HEALTHY


def _category_status(items: Iterable[Mapping[str, Any]]) -> str:
    rows = list(items)
    if not rows:
        return UNKNOWN
    statuses = {str(row.get("status") or UNKNOWN) for row in rows}
    active = statuses - {DISABLED}
    if not active:
        return DISABLED
    if HEALTHY in active and active <= {HEALTHY}:
        return HEALTHY
    if HEALTHY in active:
        return DEGRADED
    if DEGRADED in active:
        return DEGRADED
    if STALE in active:
        return STALE
    if FAILED in active:
        return FAILED
    return UNKNOWN


def evaluate_dsa_research_readiness(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate only facts owned by DSA; downstream Athena truth is excluded."""

    categories = snapshot.get("categories") if isinstance(snapshot, Mapping) else {}
    categories = categories if isinstance(categories, Mapping) else {}
    blocked = []
    degraded = []
    reasons = []
    for category in CRITICAL_CATEGORIES:
        status = str((categories.get(category) or {}).get("status") or UNKNOWN)
        if status == DEGRADED and category == "RESEARCH_MARKET_DATA":
            degraded.append(category)
            reasons.append(f"{category}:{status}")
        elif status != HEALTHY:
            blocked.append(category)
            reasons.append(f"{category}:{status}")
    news_status = str((categories.get("NEWS_SEARCH") or {}).get("status") or UNKNOWN)
    advisories = [] if news_status in {HEALTHY, DISABLED} else [f"NEWS_SEARCH:{news_status}"]
    state = READINESS_BLOCKED if blocked else (READINESS_DEGRADED if degraded or advisories else READINESS_READY)
    return {
        "DSA_RESEARCH_READINESS": state,
        "reasons": reasons,
        "blocked_categories": blocked,
        "degraded_categories": degraded,
        "advisories": advisories,
        "advisory_categories": ["NEWS_SEARCH"] if advisories else [],
        "simulation_only": True,
        "execution_authority": "ATHENA_ONLY",
        "dsa_execution_authority": False,
        "proof_order": False,
    }


def evaluate_dsa_research_admission(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Separate recoverable research observations from hard admission blockers.

    ``DSA_RESEARCH_READINESS`` is an observed-health projection.  A stale or
    transiently failed generation/provider observation must not prevent the
    next scheduler-owned natural operation from attempting the work that can
    refresh that observation.  Admission therefore checks only configuration,
    identity integrity, provider availability, and the required causal market
    context.
    """

    categories = snapshot.get("categories") if isinstance(snapshot, Mapping) else {}
    categories = categories if isinstance(categories, Mapping) else {}
    dependencies = snapshot.get("dependencies") if isinstance(snapshot, Mapping) else {}
    dependencies = dependencies if isinstance(dependencies, Mapping) else {}
    blocked: list[str] = []
    advisories: list[str] = []

    codex = dependencies.get("codex-luna")
    if not isinstance(codex, Mapping):
        inventory = [
            item for item in configured_dependency_inventory()
            if item.get("dependency_id") == "codex-luna"
        ]
        codex = inventory[0] if inventory else None
    if not isinstance(codex, Mapping) or not (
        bool(codex.get("configured")) and bool(codex.get("enabled"))
    ):
        blocked.append("LLM_RESEARCH_PROVIDER_NOT_CONFIGURED")
    else:
        metadata = codex.get("metadata") if isinstance(codex.get("metadata"), Mapping) else {}
        identity = codex.get("identity") if isinstance(codex.get("identity"), Mapping) else {}
        identity_metadata = (
            identity.get("metadata")
            if isinstance(identity.get("metadata"), Mapping)
            else {}
        )
        model = metadata.get("model") or metadata.get("expected_model") or identity_metadata.get("model")
        provider = metadata.get("provider") or metadata.get("expected_provider") or identity_metadata.get("provider")
        if model and str(model) != "gpt-5.6-luna":
            blocked.append("LLM_RESEARCH_MODEL_MISMATCH")
        if provider and str(provider) != "codex_chatgpt_oauth":
            blocked.append("LLM_RESEARCH_PROVIDER_MISMATCH")
        identity_status = codex.get("identity_status") or identity.get("status")
        if identity_status in {FAILED, DISABLED}:
            blocked.append(f"LLM_RESEARCH_IDENTITY:{identity_status}")
        elif identity_status in {None, UNKNOWN}:
            advisories.append("LLM_RESEARCH_IDENTITY_NOT_YET_OBSERVED")
        observed_status = str(codex.get("status") or UNKNOWN)
        if observed_status in {STALE, FAILED, UNKNOWN, DEGRADED}:
            advisories.append(f"LLM_RESEARCH_OBSERVED:{observed_status}")

    market_rows = [
        item for item in dependencies.values()
        if isinstance(item, Mapping) and item.get("category") == "RESEARCH_MARKET_DATA"
    ]
    if not market_rows:
        market_rows = [
            item for item in configured_dependency_inventory()
            if item.get("category") == "RESEARCH_MARKET_DATA"
        ]
    if not any(bool(item.get("configured")) and bool(item.get("enabled")) for item in market_rows):
        blocked.append("RESEARCH_MARKET_DATA_PROVIDER_NOT_CONFIGURED")
    else:
        observed_status = str(
            (categories.get("RESEARCH_MARKET_DATA") or {}).get("status") or UNKNOWN
        )
        if observed_status in {STALE, FAILED, UNKNOWN, DEGRADED}:
            advisories.append(f"RESEARCH_MARKET_DATA_OBSERVED:{observed_status}")

    context_status = str(
        (categories.get("MARKET_CONTEXT") or {}).get("status") or UNKNOWN
    )
    if context_status != HEALTHY:
        blocked.append(f"MARKET_CONTEXT_REQUIRED:{context_status}")

    return {
        "status": "BLOCKED" if blocked else "ADMITTED",
        "can_attempt": not blocked,
        "blocked_reasons": list(dict.fromkeys(blocked)),
        "advisories": list(dict.fromkeys(advisories)),
        "observed_readiness": (
            (snapshot.get("readiness") or {}).get("DSA_RESEARCH_READINESS")
            if isinstance(snapshot.get("readiness"), Mapping)
            else None
        ),
    }


def _llm_combined_status(row: Mapping[str, Any]) -> str:
    """Combine identity and generation without allowing metadata to heal generation."""
    if row.get("configured") is False or row.get("enabled") is False:
        return DISABLED
    identity = row.get("identity")
    generation = row.get("generation")
    if not isinstance(identity, Mapping):
        return UNKNOWN
    identity_status = str(identity.get("status") or UNKNOWN)
    if identity_status != HEALTHY:
        return identity_status
    if not isinstance(generation, Mapping):
        return UNKNOWN
    generation_status = str(generation.get("status") or UNKNOWN)
    if generation_status == HEALTHY:
        expires_at = _parse_timestamp(generation.get("freshness_expires_at"))
        if expires_at is not None and _now() >= expires_at:
            return STALE
    return generation_status


def _llm_observation_layer(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    observation_kind: str,
    freshness_ttl_seconds: Optional[int],
) -> Dict[str, Any]:
    """Keep a redacted, independently aging identity or generation observation."""
    previous_layer = previous.get(observation_kind)
    layer = {
        key: current.get(key)
        for key in (
            "status", "configured", "enabled", "reachable", "usable", "last_attempt_at",
            "last_success_at", "last_failure_at", "latency_ms", "records", "empty_valid",
            "data_timestamp", "max_age_seconds", "failure_class", "last_error", "metadata",
        )
    }
    if isinstance(previous_layer, Mapping):
        for key, value in previous_layer.items():
            if key not in {"metadata"} and value is not None and layer.get(key) is None:
                layer[key] = value
        layer["metadata"] = {
            **(previous_layer.get("metadata") if isinstance(previous_layer.get("metadata"), dict) else {}),
            **(layer.get("metadata") if isinstance(layer.get("metadata"), dict) else {}),
        }
        layer["observation_count"] = int(previous_layer.get("observation_count") or 0) + 1
    else:
        layer["observation_count"] = 1
    if observation_kind == "generation" and current.get("status") == HEALTHY and freshness_ttl_seconds is not None:
        expires_at = _now().timestamp() + max(0, int(freshness_ttl_seconds))
        layer["freshness_expires_at"] = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
    elif isinstance(previous_layer, Mapping):
        layer["freshness_expires_at"] = previous_layer.get("freshness_expires_at")
    return layer


class DependencyHealthStore:
    """Small atomic JSON store with transition history and restart recovery."""

    def __init__(
        self,
        path: Optional[Path | str] = None,
        *,
        transition_cooldown_seconds: int = 60,
        history_limit: int = _MAX_TRANSITIONS,
    ) -> None:
        configured_path = path or os.getenv("DSA_DEPENDENCY_HEALTH_PATH")
        self.path = Path(configured_path) if configured_path else _DEFAULT_PATH
        self.transition_cooldown_seconds = max(0, int(transition_cooldown_seconds))
        self.history_limit = max(20, int(history_limit))
        self._lock = threading.RLock()
        self._document = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(document, dict):
                document.setdefault("schema_version", 1)
                document.setdefault("dependencies", {})
                document.setdefault("categories", {})
                document.setdefault("transitions", [])
                document.setdefault("alerts", [])
                document.setdefault("monitor", self.monitor_config())
                return document
        except (OSError, ValueError, TypeError):
            pass
        return {
            "schema_version": 1,
            "updated_at": None,
            "dependencies": {},
            "categories": {},
            "transitions": [],
            "alerts": [],
            "monitor": self.monitor_config(),
            "readiness": {
                "DSA_RESEARCH_READINESS": READINESS_BLOCKED,
                "reasons": ["DEPENDENCY_HEALTH_NOT_OBSERVED"],
            },
            "research_admission": {
                "status": "BLOCKED",
                "can_attempt": False,
                "blocked_reasons": ["DEPENDENCY_HEALTH_NOT_OBSERVED"],
            },
        }

    def monitor_config(self) -> Dict[str, Any]:
        return {
            "persistent": True,
            "read_only": True,
            "interval_seconds": max(
                30,
                int(os.getenv("DSA_DEPENDENCY_MONITOR_INTERVAL_SECONDS", str(_DEFAULT_INTERVAL_SECONDS))),
            ),
            "transition_cooldown_seconds": self.transition_cooldown_seconds,
            "authority_loop": False,
        }

    def _persist_locked(self) -> None:
        self._document["updated_at"] = _iso()
        self._document["monitor"] = self.monitor_config()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(self._document, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError:
            # Health reporting must never turn a research request into an action.
            return

    def _record_transition_locked(self, previous: Mapping[str, Any], current: Mapping[str, Any]) -> None:
        old_status = previous.get("status")
        new_status = current.get("status")
        if not previous or (old_status or UNKNOWN) == new_status:
            return
        previous_event = previous.get("last_transition_at")
        if previous_event:
            elapsed = (_now() - (_parse_timestamp(previous_event) or _now())).total_seconds()
            if elapsed < self.transition_cooldown_seconds:
                return
        event = {
            "timestamp": current.get("last_attempt_at") or _iso(),
            "dependency_id": current.get("dependency_id"),
            "category": current.get("category"),
            "from": old_status or UNKNOWN,
            "to": new_status,
            "failure_class": current.get("failure_class"),
            "fallback_from": current.get("fallback_from"),
            "fallback_to": current.get("fallback_to"),
        }
        recovered = new_status == HEALTHY and old_status not in {None, HEALTHY}
        critical_failure = (
            current.get("category") in CRITICAL_CATEGORIES
            and new_status in {FAILED, STALE, UNKNOWN}
        )
        event["alert_id"] = f"{current.get('dependency_id')}:{new_status}:{event['timestamp']}"
        self._document.setdefault("transitions", []).append(event)
        self._document["transitions"] = self._document["transitions"][-self.history_limit :]
        self._document.setdefault("alerts", []).append({
            **event,
            "kind": "dependency_health_transition",
            "severity": "info" if recovered else ("critical" if critical_failure else "warning"),
            "recovery": recovered,
        })
        self._document["alerts"] = self._document["alerts"][-min(self.history_limit, _MAX_ALERTS) :]

    def record_result(
        self,
        dependency_id: str,
        *,
        category: str,
        configured: bool = True,
        enabled: bool = True,
        role: str = "AUXILIARY",
        priority: int = 99,
        endpoint: Optional[str] = None,
        success: Optional[bool] = None,
        reachable: Optional[bool] = None,
        usable: Optional[bool] = None,
        records: int = 0,
        empty_valid: bool = False,
        latency_ms: Optional[int] = None,
        failure_class_name: Optional[str] = None,
        error: Optional[Any] = None,
        data_timestamp: Optional[str] = None,
        max_age_seconds: Optional[int] = None,
        fallback_from: Optional[str] = None,
        fallback_to: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        observation_kind: Optional[str] = None,
        freshness_ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        dependency_id = _safe_text(dependency_id, 100) or "unknown"
        category = _safe_text(category, 80) or "UNKNOWN"
        attempted_at = _iso()
        status = _status_for_observation(
            configured=configured,
            enabled=enabled,
            success=success,
            reachable=reachable,
            usable=usable,
            records=max(0, int(records or 0)),
            empty_valid=bool(empty_valid),
            data_timestamp=data_timestamp,
            max_age_seconds=max_age_seconds,
        )
        with self._lock:
            previous = dict(self._document.setdefault("dependencies", {}).get(dependency_id) or {})
            current = {
                "dependency_id": dependency_id,
                "category": category,
                "configured": bool(configured),
                "enabled": bool(enabled),
                "role": _safe_text(role, 40) or "AUXILIARY",
                "priority": int(priority),
                "endpoint": _safe_endpoint(endpoint),
                "status": status if status in HEALTH_STATUSES else UNKNOWN,
                "reachable": bool(reachable) if reachable is not None else None,
                "usable": bool(usable) if usable is not None else status == HEALTHY,
                "last_attempt_at": attempted_at,
                "last_success_at": attempted_at if success is True else previous.get("last_success_at"),
                "last_failure_at": attempted_at if success is False else previous.get("last_failure_at"),
                "latency_ms": max(0, int(latency_ms)) if latency_ms is not None else None,
                "records": max(0, int(records or 0)),
                "empty_valid": bool(empty_valid),
                "data_timestamp": _safe_text(data_timestamp, 80),
                "max_age_seconds": max_age_seconds,
                "failure_class": _failure_class(failure_class_name or error),
                "last_error": _safe_text(error),
                "fallback_from": _safe_text(fallback_from, 80),
                "fallback_to": _safe_text(fallback_to, 80),
                "last_transition_at": previous.get("last_transition_at"),
                "observation_count": int(previous.get("observation_count") or 0) + 1,
                "metadata": {
                    **(previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}),
                    **_safe_metadata(metadata),
                },
            }
            if dependency_id in {"codex-luna", "qwen-omlx"} and observation_kind in {"identity", "generation"}:
                for other_kind in ("identity", "generation"):
                    if other_kind != observation_kind and isinstance(previous.get(other_kind), Mapping):
                        current[other_kind] = dict(previous[other_kind])
                current[observation_kind] = _llm_observation_layer(
                    current,
                    previous,
                    observation_kind=observation_kind,
                    freshness_ttl_seconds=(
                        freshness_ttl_seconds
                        if freshness_ttl_seconds is not None
                        else int(os.getenv(
                            "DSA_CODEX_GENERATION_HEALTH_TTL_SECONDS",
                            os.getenv(
                                "DSA_QWEN_GENERATION_HEALTH_TTL_SECONDS",
                                str(_DEFAULT_LLM_GENERATION_TTL_SECONDS),
                            ),
                        ))
                    ),
                )
                current["identity_status"] = (current.get("identity") or {}).get("status")
                current["generation_status"] = (current.get("generation") or {}).get("status")
                current["generation_freshness_expires_at"] = (current.get("generation") or {}).get("freshness_expires_at")
                current["status"] = _llm_combined_status(current)
                current["usable"] = current["status"] == HEALTHY
                identity_layer = current.get("identity") or previous.get("identity") or {}
                current["reachable"] = identity_layer.get("reachable", current.get("reachable"))
                generation_layer = current.get("generation") or previous.get("generation") or {}
                current["last_success_at"] = generation_layer.get("last_success_at")
                current["last_failure_at"] = generation_layer.get("last_failure_at")
                current["failure_class"] = generation_layer.get("failure_class") or (
                    "GENERATION_HEALTH_EXPIRED" if current["status"] == STALE else None
                )
                current["last_error"] = generation_layer.get("last_error")
            if current.get("status") != previous.get("status"):
                current["last_transition_at"] = attempted_at
            self._record_transition_locked(previous, current)
            self._document["dependencies"][dependency_id] = current
            self._rebuild_categories_locked()
            self._persist_locked()
            return dict(current)

    def _rebuild_categories_locked(self) -> None:
        llm = self._document.get("dependencies", {}).get("codex-luna")
        if isinstance(llm, dict) and ("identity" in llm or "generation" in llm):
            combined = _llm_combined_status(llm)
            llm["status"] = combined
            llm["usable"] = combined == HEALTHY
            llm["identity_status"] = (llm.get("identity") or {}).get("status")
            llm["generation_status"] = (llm.get("generation") or {}).get("status")
            llm["generation_freshness_expires_at"] = (llm.get("generation") or {}).get("freshness_expires_at")
            if combined == STALE:
                llm["failure_class"] = "GENERATION_HEALTH_EXPIRED"
        grouped: Dict[str, list[Mapping[str, Any]]] = {}
        for row in self._document.get("dependencies", {}).values():
            data_timestamp = _parse_timestamp(row.get("data_timestamp"))
            max_age_seconds = row.get("max_age_seconds")
            if (
                row.get("status") in {HEALTHY, DEGRADED}
                and data_timestamp is not None
                and max_age_seconds is not None
                and (_now() - data_timestamp).total_seconds() > int(max_age_seconds)
            ):
                row["status"] = STALE
                row["usable"] = False
                row["failure_class"] = "FRESHNESS_EXPIRED"
            if row.get("dependency_id") == "qwen-omlx" and row.get("category") == "LLM_RESEARCH":
                # Preserve old local-Qwen evidence on disk without allowing a
                # dormant/local provider to make Codex/Luna research ready.
                continue
            grouped.setdefault(str(row.get("category") or "UNKNOWN"), []).append(row)
        categories: Dict[str, Any] = {}
        for category, rows in grouped.items():
            statuses = _category_status(rows)

            def _freshness_expiry(row: Mapping[str, Any]) -> Optional[str]:
                llm_expiry = (row.get("generation") or {}).get("freshness_expires_at")
                if llm_expiry or row.get("generation_freshness_expires_at"):
                    return llm_expiry or row.get("generation_freshness_expires_at")
                timestamp = _parse_timestamp(row.get("data_timestamp"))
                max_age = row.get("max_age_seconds")
                if timestamp is not None and max_age is not None:
                    return (timestamp + timedelta(seconds=int(max_age))).isoformat()
                return None

            source_events = [
                row.get("data_timestamp") or row.get("last_success_at") or row.get("last_attempt_at")
                for row in rows
                if row.get("data_timestamp") or row.get("last_success_at") or row.get("last_attempt_at")
            ]
            fresh_until = [expiry for row in rows if (expiry := _freshness_expiry(row))]
            reason = next((
                f"{row.get('dependency_id')}:{row.get('status')}"
                for row in rows if row.get("status") not in {HEALTHY, DISABLED}
            ), None)
            categories[category] = {
                "key": category,
                "category": category,
                "owner_component": "DSA",
                "purpose": _CATEGORY_PURPOSE.get(category, "DSA research dependency"),
                "status": statuses,
                "reason": reason,
                "reason_code": reason,
                "observed_at": _iso(),
                "source_event_at": max(source_events) if source_events else None,
                "fresh_until": min(fresh_until) if fresh_until else None,
                "stale_at": min(fresh_until) if fresh_until else None,
                "source": "dsa_dependency_health_store",
                "dependency_ids": [row.get("dependency_id") for row in rows],
                "critical": category in CRITICAL_CATEGORIES,
                "reasons": [
                    f"{row.get('dependency_id')}:{row.get('status')}"
                    for row in rows
                    if row.get("status") not in {HEALTHY, DISABLED}
                ],
            }
        self._document["categories"] = categories
        self._document["readiness"] = evaluate_dsa_research_readiness(
            {"categories": categories}
        )
        self._document["research_admission"] = evaluate_dsa_research_admission(
            {"categories": categories, "dependencies": self._document.get("dependencies", {})}
        )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._rebuild_categories_locked()
            return json.loads(json.dumps(self._document, ensure_ascii=False))

    def record_inventory(self, inventory: Iterable[Mapping[str, Any]]) -> None:
        """Persist configuration without replacing the last real observation.

        Inventory refreshes are not provider probes.  A refresh must therefore
        preserve the last real success/failure, latency and freshness evidence;
        otherwise the monitor would turn every dependency into UNKNOWN before
        a caller has a chance to report its next real request.
        """
        with self._lock:
            dependencies = self._document.setdefault("dependencies", {})
            for item in inventory:
                dependency_id = _safe_text(item.get("dependency_id") or item.get("name"), 100) or "unknown"
                category = _safe_text(item.get("category"), 80) or "UNKNOWN"
                configured = bool(item.get("configured", False))
                enabled = bool(item.get("enabled", False))
                previous = dict(dependencies.get(dependency_id) or {})
                current = {
                    **previous,
                    "dependency_id": dependency_id,
                    "category": category,
                    "configured": configured,
                    "enabled": enabled,
                    "role": _safe_text(item.get("role") or "AUXILIARY", 40) or "AUXILIARY",
                    "priority": int(item.get("priority") or 99),
                    "endpoint": _safe_endpoint(item.get("endpoint")),
                    "metadata": {
                        **(previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}),
                        **_safe_metadata(item),
                    },
                }
                if not configured or not enabled:
                    current["status"] = DISABLED
                    current["reachable"] = False
                    current["usable"] = False
                elif previous.get("status") == DISABLED:
                    current["status"] = UNKNOWN
                    current["reachable"] = None
                    current["usable"] = None
                else:
                    current["status"] = previous.get("status") or UNKNOWN
                if current.get("status") != previous.get("status") and previous:
                    current["last_transition_at"] = _iso()
                    self._record_transition_locked(previous, current)
                dependencies[dependency_id] = current
            self._rebuild_categories_locked()
            self._persist_locked()


def _env_configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def configured_dependency_inventory() -> list[Dict[str, Any]]:
    """Return the non-secret runtime inventory used by the monitor/API."""
    try:
        from src.config import setup_env

        setup_env()
    except Exception:
        pass
    searx_urls = [item.strip() for item in os.getenv("SEARXNG_BASE_URLS", "").split(",") if item.strip()]
    inventory: list[Dict[str, Any]] = [
        {
            "dependency_id": "codex-luna",
            "category": "LLM_RESEARCH",
            "configured": os.getenv("GENERATION_BACKEND", "").strip().lower() == "codex_cli"
            or os.getenv("AGENT_BACKEND", "").strip().lower() == "codex_app_server",
            "enabled": os.getenv("GENERATION_BACKEND", "").strip().lower() == "codex_cli"
            or os.getenv("AGENT_BACKEND", "").strip().lower() == "codex_app_server",
            "role": "PRIMARY",
            "priority": 1,
            "endpoint": "codex://chatgpt-oauth",
            "model": os.getenv("CODEX_CLI_MODEL", "gpt-5.6-luna"),
            "provider": "codex_chatgpt_oauth",
            "auth_mode": "codex_managed_chatgpt_oauth",
        },
        {"dependency_id": "bocha", "category": "NEWS_SEARCH", "configured": _env_configured("BOCHA_API_KEYS"), "enabled": _env_configured("BOCHA_API_KEYS"), "role": "PRIMARY", "priority": 1, "endpoint": "https://api.bocha.cn/v1/web-search"},
        {"dependency_id": "searxng", "category": "NEWS_SEARCH", "configured": bool(searx_urls), "enabled": bool(searx_urls), "role": "FALLBACK", "priority": 2, "endpoint": searx_urls[0] if searx_urls else None},
        {"dependency_id": "searxng-public-discovery", "category": "NEWS_SEARCH", "configured": os.getenv("SEARXNG_PUBLIC_INSTANCES_ENABLED", "false").lower() == "true", "enabled": os.getenv("SEARXNG_PUBLIC_INSTANCES_ENABLED", "false").lower() == "true", "role": "AUXILIARY", "priority": 99, "endpoint": "https://searx.space/data/instances.json"},
        {"dependency_id": "tavily", "category": "NEWS_SEARCH", "configured": _env_configured("TAVILY_API_KEYS"), "enabled": _env_configured("TAVILY_API_KEYS"), "role": "AUXILIARY", "priority": 99, "endpoint": "https://api.tavily.com"},
        {"dependency_id": "brave", "category": "NEWS_SEARCH", "configured": _env_configured("BRAVE_API_KEYS"), "enabled": _env_configured("BRAVE_API_KEYS"), "role": "AUXILIARY", "priority": 99, "endpoint": "https://api.search.brave.com"},
        {"dependency_id": "serpapi", "category": "NEWS_SEARCH", "configured": _env_configured("SERPAPI_API_KEYS"), "enabled": _env_configured("SERPAPI_API_KEYS"), "role": "AUXILIARY", "priority": 99, "endpoint": "https://serpapi.com"},
        {"dependency_id": "minimax-search", "category": "NEWS_SEARCH", "configured": _env_configured("MINIMAX_API_KEYS"), "enabled": _env_configured("MINIMAX_API_KEYS"), "role": "AUXILIARY", "priority": 99, "endpoint": "https://api.minimax.chat"},
        {"dependency_id": "anspire", "category": "NEWS_SEARCH", "configured": _env_configured("ANSPIRE_API_KEYS"), "enabled": _env_configured("ANSPIRE_API_KEYS"), "role": "AUXILIARY", "priority": 99, "endpoint": "https://api.anspire.cn"},
        {"dependency_id": "tushare", "category": "RESEARCH_MARKET_DATA", "configured": _env_configured("TUSHARE_TOKEN"), "enabled": _env_configured("TUSHARE_TOKEN"), "role": "PRIMARY", "priority": 1, "endpoint": "https://api.tushare.pro"},
        {"dependency_id": "tickflow", "category": "RESEARCH_MARKET_DATA", "configured": _env_configured("TICKFLOW_API_KEY"), "enabled": _env_configured("TICKFLOW_API_KEY"), "role": "AUXILIARY", "priority": 99},
        {"dependency_id": "efinance", "category": "RESEARCH_MARKET_DATA", "configured": True, "enabled": True, "role": "FALLBACK", "priority": 2, "endpoint": "https://www.efinance.com.cn"},
        {"dependency_id": "sina", "category": "RESEARCH_MARKET_DATA", "configured": True, "enabled": True, "role": "FALLBACK", "priority": 3, "endpoint": "https://finance.sina.com.cn"},
        {"dependency_id": "eastmoney", "category": "RESEARCH_MARKET_DATA", "configured": True, "enabled": True, "role": "FALLBACK", "priority": 4, "endpoint": "https://datacenter.eastmoney.com"},
        {"dependency_id": "akshare", "category": "RESEARCH_MARKET_DATA", "configured": True, "enabled": True, "role": "FALLBACK", "priority": 3, "endpoint": "https://akshare.akfamily.xyz"},
    ]
    return inventory


_DEFAULT_STORE: Optional[DependencyHealthStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_dependency_health_store() -> DependencyHealthStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = DependencyHealthStore()
        return _DEFAULT_STORE


class DependencyHealthMonitor:
    """One lightweight, read-only monitor owner for the DSA process."""

    def __init__(self, store: Optional[DependencyHealthStore] = None, *, interval_seconds: Optional[int] = None) -> None:
        self.store = store or get_dependency_health_store()
        self.interval_seconds = max(30, int(interval_seconds or self.store.monitor_config()["interval_seconds"]))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def once(self) -> Dict[str, Any]:
        self.store.record_inventory(configured_dependency_inventory())
        try:
            from src.services.codex_health import probe_codex_identity

            identity = probe_codex_identity()
            self.store.record_result(
                "codex-luna",
                category="LLM_RESEARCH",
                configured=identity.get("configured", False),
                enabled=identity.get("enabled", False),
                role="PRIMARY",
                priority=1,
                endpoint=identity.get("endpoint"),
                success=identity.get("success"),
                reachable=identity.get("reachable"),
                usable=identity.get("usable"),
                # Identity is a successful executable/login/model observation;
                # it does not expose a loaded-record count like a data source.
                records=1 if identity.get("success") is True else 0,
                empty_valid=False,
                latency_ms=identity.get("latency_ms"),
                failure_class_name=identity.get("failure_class"),
                error=identity.get("error"),
                metadata=identity,
                observation_kind="identity",
            )
        except Exception as exc:  # pragma: no cover - defensive monitor boundary
            self.store.record_result(
                "codex-luna",
                category="LLM_RESEARCH",
                configured=True,
                enabled=True,
                role="PRIMARY",
                priority=1,
                success=False,
                reachable=False,
                usable=False,
                failure_class_name=type(exc).__name__,
                error=str(exc),
                observation_kind="identity",
            )
        return self.store.snapshot()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.once()
            except Exception:
                # A health thread cannot be allowed to become a second
                # authority loop or to crash the research API.
                pass
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pallas-010-health-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None


__all__ = [
    "HEALTHY", "DEGRADED", "FAILED", "STALE", "UNKNOWN", "DISABLED",
    "READINESS_READY", "READINESS_DEGRADED", "READINESS_BLOCKED",
    "CRITICAL_CATEGORIES", "DependencyHealthStore", "DependencyHealthMonitor",
    "configured_dependency_inventory", "get_dependency_health_store",
    "evaluate_dsa_research_readiness", "evaluate_dsa_research_admission",
]
