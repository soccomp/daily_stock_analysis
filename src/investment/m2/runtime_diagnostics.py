"""Safe, observational explanations for persisted Single Brain cycle failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RuntimeFailureExplanation:
    stage: str
    code: str
    summary: str


_SUMMARIES = {
    "AI_QUOTA_EXHAUSTED": "AI 分析额度不足",
    "AI_SERVICE_UNAVAILABLE": "AI 分析服务暂时不可用",
    "RESEARCH_DATA_UNAVAILABLE": "研究所需数据暂时不可用",
    "RESEARCH_INCOMPLETE": "研究阶段未完成，具体原因待确认",
    "SNAPSHOT_STALE": "账户快照已过期",
    "SNAPSHOT_TIME_INVALID": "账户快照时间异常",
    "SNAPSHOT_UNAVAILABLE": "账户快照暂时不可用",
    "SNAPSHOT_UNRECONCILED": "账户快照尚未完成核对",
    "RISK_POLICY_UNAVAILABLE": "风险政策暂时不可用",
    "DECISION_INCOMPLETE": "投资决策阶段未完成",
    "EXECUTION_PENDING": "执行事实尚待核对",
    "CYCLE_FAILURE": "运行过程中发生错误",
}


def _explanation(stage: str, code: str) -> RuntimeFailureExplanation:
    return RuntimeFailureExplanation(stage=stage, code=code, summary=_SUMMARIES[code])


def classify_runtime_failure(
    reasons: Iterable[str | None],
    *,
    research_incomplete: bool = False,
) -> RuntimeFailureExplanation:
    """Map persisted evidence to a small user-safe vocabulary without exposing it."""

    generic_cycle_reasons = {
        "no shadow decision lineage was persisted",
        "one or more symbols failed closed",
    }
    for raw_reason in reasons:
        reason = str(raw_reason or "").strip()
        if not reason or reason.lower() in generic_cycle_reasons:
            continue
        normalized = reason.casefold().replace("-", "_")

        marker = "runtime_reason="
        if marker in normalized:
            code = normalized.split(marker, 1)[1].split()[0].strip(";,:[]").upper()
            for stage, allowed in (
                ("RESEARCH", {"AI_QUOTA_EXHAUSTED", "AI_SERVICE_UNAVAILABLE", "RESEARCH_DATA_UNAVAILABLE", "RESEARCH_INCOMPLETE"}),
                (
                    "AUTHORITY_INPUT",
                    {
                        "SNAPSHOT_STALE",
                        "SNAPSHOT_TIME_INVALID",
                        "SNAPSHOT_UNAVAILABLE",
                        "SNAPSHOT_UNRECONCILED",
                        "RISK_POLICY_UNAVAILABLE",
                    },
                ),
                ("DECISION", {"DECISION_INCOMPLETE"}),
                ("EXECUTION", {"EXECUTION_PENDING"}),
            ):
                if code in allowed:
                    return _explanation(stage, code)

        if "snapshot" in normalized or "portfoliosnapshot" in normalized:
            if any(token in normalized for token in ("future_dated", "future dated", "未来")):
                return _explanation("AUTHORITY_INPUT", "SNAPSHOT_TIME_INVALID")
            if any(token in normalized for token in ("stale", "已过期")):
                return _explanation("AUTHORITY_INPUT", "SNAPSHOT_STALE")
            if any(token in normalized for token in ("not reconciled", "unreconciled", "核对")):
                return _explanation("AUTHORITY_INPUT", "SNAPSHOT_UNRECONCILED")
            return _explanation("AUTHORITY_INPUT", "SNAPSHOT_UNAVAILABLE")
        if "riskpolicy" in normalized or "risk policy" in normalized:
            return _explanation("AUTHORITY_INPUT", "RISK_POLICY_UNAVAILABLE")
        research_context = any(token in normalized for token in (
            "analysis", "research", "llm", "provider", "generation", "ai ", "分析", "研究",
        ))
        if research_context and any(token in normalized for token in (
            "quota", "rate_limit", "ratelimit", "resource_exhausted",
            "too many requests", "429", "额度", "限流",
        )):
            return _explanation("RESEARCH", "AI_QUOTA_EXHAUSTED")
        if research_context and any(token in normalized for token in (
            "backend_not_configured", "api key", "api_key", "login_required",
            "unavailable", "connection refused", "connection error", "timeout",
        )):
            return _explanation("RESEARCH", "AI_SERVICE_UNAVAILABLE")
        explicit_research_data = any(token in normalized for token in (
            "research data", "market data", "研究所需数据",
        ))
        weak_data_failure = any(token in normalized for token in (
            "data unavailable", "no data", "prerequisite",
        ))
        if explicit_research_data or research_context and weak_data_failure:
            return _explanation("RESEARCH", "RESEARCH_DATA_UNAVAILABLE")
        if any(token in normalized for token in (
            "real dsa analysis", "analysis did not complete", "analysis result",
            "research", "llm", "分析未", "研究阶段",
        )):
            return _explanation("RESEARCH", "RESEARCH_INCOMPLETE")
        if any(token in normalized for token in ("shadow wiring", "decision", "资本配置")):
            return _explanation("DECISION", "DECISION_INCOMPLETE")
        if any(token in normalized for token in ("pending_reconciliation", "reconciliation", "m3 recovery", "execution")):
            return _explanation("EXECUTION", "EXECUTION_PENDING")

    if research_incomplete:
        return _explanation("RESEARCH", "RESEARCH_INCOMPLETE")
    return _explanation("CYCLE", "CYCLE_FAILURE")


def analysis_failure_marker(error_message: object) -> str:
    """Persist only a stable safe category from an unsuccessful AnalysisResult."""

    explanation = classify_runtime_failure(
        (
            None
            if error_message is None
            else f"analysis provider failure: {error_message}",
        ),
        research_incomplete=True,
    )
    if explanation.stage != "RESEARCH":
        explanation = _explanation("RESEARCH", "RESEARCH_INCOMPLETE")
    return f"runtime_reason={explanation.code}"
