"""Deterministic Pallas decision output built from existing structured evidence.

The proposal path uses this module as the decision authority.  Narrative AI may
explain a persisted result elsewhere, but it is never an input to the action.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from src.analyzer import AnalysisResult
from src.report_language import normalize_report_language
from src.schemas.decision_action import localize_action_label
from src.schemas.decision_scale import action_for_score, normalize_score
from src.stock_analyzer import TrendAnalysisResult


RULE_MODEL_ID = "pallas/rules-v1"
RULE_VERSION = "pallas-deterministic-decision-v1"
SIMULATION_RELAXED_RULES_PROFILE = "SIMULATION_RELAXED_V1"
SIMULATION_STOP_LOSS_PCT = Decimal("0.12")
SIMULATION_TAKE_PROFIT_PCT = Decimal("0.25")


def build_rule_analysis_result(
    *,
    code: str,
    name: str,
    trend_result: TrendAnalysisResult | None,
    enhanced_context: Mapping[str, Any],
    decision_context: Mapping[str, Any] | None = None,
    fundamental_context: Mapping[str, Any] | None = None,
    market_structure_context: Mapping[str, Any] | None = None,
    report_language: str = "zh",
) -> AnalysisResult:
    """Build one auditable action without invoking an LLM or news search."""

    language = normalize_report_language(report_language)
    decision = dict(decision_context or {})
    has_position = bool(decision.get("has_position"))
    simulation_relaxed = bool(decision.get("simulation_relaxed"))
    score = normalize_score(getattr(trend_result, "signal_score", None))
    canonical_action = action_for_score(score)
    action, guardrail_reason = _resolve_action(
        canonical_action=canonical_action,
        trend_result=trend_result,
        has_position=has_position,
        simulation_relaxed=simulation_relaxed,
    )
    exit_action, exit_reason = _simulation_exit_override(
        decision_context=decision,
        trend_result=trend_result,
        enhanced_context=enhanced_context,
        simulation_relaxed=simulation_relaxed,
    )
    if exit_action is not None:
        action = exit_action
        guardrail_reason = (
            f"{guardrail_reason}；{exit_reason}"
            if guardrail_reason
            else exit_reason
        )
    price_plan, fallback_price_plan = _price_plan_with_status(
        trend_result,
        enhanced_context,
        simulation_relaxed=simulation_relaxed,
    )
    if action in {"buy", "add"} and price_plan is None:
        action = "hold" if has_position else "watch"
        guardrail_reason = "规则买入条件成立，但缺少可验证的支撑、压力或当前价格，降级为观望"
    elif action in {"buy", "add"} and fallback_price_plan:
        fallback_reason = "模拟档位使用固定价格兜底（仅用于 simulation-only）"
        guardrail_reason = (
            f"{guardrail_reason}；{fallback_reason}"
            if guardrail_reason
            else fallback_reason
        )

    display_score = score if score is not None else 50
    decision_type = (
        "buy"
        if action in {"buy", "add"}
        else "sell"
        if action in {"reduce", "sell"}
        else "hold"
    )
    action_label = localize_action_label(action, language) or action
    trend_label = _enum_value(getattr(trend_result, "trend_status", None)) or "数据不足"
    reasons = _text_items(getattr(trend_result, "signal_reasons", None))
    risks = _text_items(getattr(trend_result, "risk_factors", None))
    summary = (
        f"规则引擎按技术评分 {display_score}/100、趋势状态“{trend_label}”"
        f"给出“{action_label}”；该动作未使用 AI 结论。"
    )
    if guardrail_reason:
        summary = f"{summary} {guardrail_reason}。"

    current_price = _current_price(trend_result, enhanced_context)
    position_target = _reduce_target(decision) if action == "reduce" else None
    sniper_points: dict[str, Any] = {}
    if price_plan is not None and action in {"buy", "add"}:
        sniper_points = {
            "ideal_buy": price_plan[0],
            "secondary_buy": price_plan[1],
            "stop_loss": price_plan[2],
            "take_profit": price_plan[3],
        }

    dashboard: dict[str, Any] = {
        "core_conclusion": {
            "one_sentence": summary,
            "signal_type": action_label,
            "time_sensitivity": "等待下一轮规则复核" if action in {"hold", "watch"} else "本轮有效期内",
            "position_advice": {
                "no_position": action_label if not has_position else "不适用",
                "has_position": action_label if has_position else "不适用",
            },
        },
        "data_perspective": {
            "price_position": {
                "current_price": current_price,
                "support_level": price_plan[2] if price_plan else _first_positive(
                    getattr(trend_result, "support_levels", None)
                ),
                "resistance_level": price_plan[3] if price_plan else _first_positive(
                    getattr(trend_result, "resistance_levels", None)
                ),
            },
        },
        "intelligence": {"risk_alerts": risks},
        "battle_plan": {
            "sniper_points": sniper_points,
            "position_strategy": {
                "suggested_position": (
                    f"{(position_target * Decimal('100')):.6f}%"
                    if position_target is not None
                    else ""
                )
            },
            "action_checklist": reasons,
        },
        "decision_score_calibration": {
            "scale_version": "decision-scale-v1",
            "score": display_score,
            "canonical_action": canonical_action,
            "final_action": action,
            "guardrail_reason": guardrail_reason,
        },
        "decision_stability": {
            "applied": bool(guardrail_reason),
            "reason": guardrail_reason,
        },
        "rule_decision": {
            "version": RULE_VERSION,
            "profile": (
                SIMULATION_RELAXED_RULES_PROFILE
                if simulation_relaxed
                else "STRICT_RULES"
            ),
            "authority": "RULES",
            "ai_used_for_action": False,
            "ai_role": "OPTIONAL_EXPLANATION_ONLY",
            "simulation_relaxed": simulation_relaxed,
            "fallback_price_plan": fallback_price_plan,
            "candidate_source": str(decision.get("candidate_source") or "UNKNOWN"),
            "has_position": has_position,
            "input_score": score,
            "canonical_score_action": canonical_action,
            "final_action": action,
            "signal_reasons": reasons,
            "risk_factors": risks,
            "exit_rules": {
                "enabled": simulation_relaxed,
                "stop_loss_pct": float(SIMULATION_STOP_LOSS_PCT),
                "take_profit_pct": float(SIMULATION_TAKE_PROFIT_PCT),
                "momentum_rule": "change_60d<0 且趋势或 MACD 走弱时减仓",
                "trigger": exit_reason,
            },
        },
    }

    result = AnalysisResult(
        code=code,
        name=name,
        sentiment_score=display_score,
        trend_prediction=trend_label,
        operation_advice=action_label,
        decision_type=decision_type,
        confidence_level="中" if score is not None else "低",
        report_language=language,
        action=action,
        action_label=action_label,
        dashboard=dashboard,
        trend_analysis=_trend_description(trend_result),
        technical_analysis=_trend_description(trend_result),
        fundamental_analysis=_fundamental_description(fundamental_context),
        sector_position=_market_structure_description(market_structure_context),
        analysis_summary=summary,
        key_points="；".join(reasons),
        risk_warning="；".join(risks) or "规则未识别到额外技术风险；仍需遵守 Athena 风控。",
        buy_reason="；".join(reasons),
        market_snapshot={
            "today": dict(enhanced_context.get("today") or {}),
            "realtime": dict(enhanced_context.get("realtime") or {}),
        },
        search_performed=False,
        data_sources="pallas:rules,trend:structured,market:structured",
        current_price=current_price,
        change_pct=_float_or_none((enhanced_context.get("realtime") or {}).get("change_pct")),
        model_used=RULE_MODEL_ID,
        fundamental_context=dict(fundamental_context or {}),
        market_structure_context=dict(market_structure_context or {}),
    )
    # Existing action resolvers inspect this runtime field before persistence;
    # the durable copy remains in dashboard.decision_stability.
    result.guardrail_reason = guardrail_reason
    return result


def _resolve_action(
    *,
    canonical_action: str | None,
    trend_result: TrendAnalysisResult | None,
    has_position: bool,
    simulation_relaxed: bool = False,
) -> tuple[str, str]:
    if trend_result is None or canonical_action is None:
        return ("hold" if has_position else "watch"), "缺少完整趋势评分，规则按安全模式观望"
    if canonical_action == "buy":
        signal_name = str(getattr(getattr(trend_result, "buy_signal", None), "name", "")).lower()
        if signal_name not in {"buy", "strong_buy"}:
            if simulation_relaxed and _is_non_bearish_trend(trend_result):
                return (
                    "add" if has_position else "buy",
                    "模拟档位放宽：趋势评分已进入买入区间，先执行一笔可回溯模拟动作",
                )
            return ("hold" if has_position else "watch"), "分数进入买入区间，但趋势形态尚未确认买点"
        return ("add" if has_position else "buy"), ""
    if canonical_action in {"reduce", "sell"}:
        if has_position:
            return canonical_action, ""
        return "watch", "空仓状态不执行减仓或卖出动作"
    return ("hold" if has_position else "watch"), ""


def _simulation_exit_override(
    *,
    decision_context: Mapping[str, Any],
    trend_result: TrendAnalysisResult | None,
    enhanced_context: Mapping[str, Any],
    simulation_relaxed: bool,
) -> tuple[str | None, str | None]:
    """Apply the deliberately small simulation-only exit rules.

    The active proposal path must remain useful before the full PALLAS-008
    lifecycle is wired in.  These exits use only an authoritative average cost,
    the current price, and an existing 60-day momentum/trend signal.  Missing
    fields fail closed and leave the score-based action unchanged.
    """

    if not simulation_relaxed or not bool(decision_context.get("has_position")):
        return None, None

    current = _current_price(trend_result, enhanced_context)
    average_cost = _decimal_or_none(decision_context.get("position_avg_cost"))
    if current is not None and average_cost is not None and average_cost > 0:
        current_value = Decimal(str(current))
        if current_value > 0:
            return_ratio = (current_value - average_cost) / average_cost
            if return_ratio <= -SIMULATION_STOP_LOSS_PCT:
                return "sell", "模拟退出：相对持仓成本达到止损阈值（-12%）"
            if return_ratio >= SIMULATION_TAKE_PROFIT_PCT:
                return "sell", "模拟退出：相对持仓成本达到止盈阈值（+25%）"

    realtime = enhanced_context.get("realtime")
    change_60d = (
        _decimal_or_none(realtime.get("change_60d"))
        if isinstance(realtime, Mapping)
        else None
    )
    trend_name = str(getattr(getattr(trend_result, "trend_status", None), "name", "")).upper()
    macd_name = str(getattr(getattr(trend_result, "macd_status", None), "name", "")).upper()
    bearish_trend = trend_name in {"WEAK_BEAR", "BEAR", "STRONG_BEAR"}
    bearish_macd = macd_name in {"BEARISH", "CROSSING_DOWN", "DEATH_CROSS"}
    if change_60d is not None and change_60d < 0 and (bearish_trend or bearish_macd):
        return "reduce", "模拟退出：60日动量为负且趋势或 MACD 走弱，先减仓"
    return None, None


def _price_plan(
    trend_result: TrendAnalysisResult | None,
    enhanced_context: Mapping[str, Any],
    *,
    simulation_relaxed: bool = False,
) -> tuple[float, float, float, float] | None:
    return _price_plan_with_status(
        trend_result,
        enhanced_context,
        simulation_relaxed=simulation_relaxed,
    )[0]


def _price_plan_with_status(
    trend_result: TrendAnalysisResult | None,
    enhanced_context: Mapping[str, Any],
    *,
    simulation_relaxed: bool,
) -> tuple[tuple[float, float, float, float] | None, bool]:
    realtime = enhanced_context.get("realtime")
    current = _current_price(trend_result, enhanced_context)
    if current is None:
        return None, False
    if (
        isinstance(realtime, Mapping)
        and realtime.get("is_stale") is True
        and not simulation_relaxed
    ):
        return None, False
    supports = sorted(
        value
        for value in _positive_values(
            getattr(trend_result, "support_levels", None),
            getattr(trend_result, "ma5", None),
            getattr(trend_result, "ma10", None),
            getattr(trend_result, "ma20", None),
        )
        if value < current
    )
    resistances = sorted(
        value
        for value in _positive_values(getattr(trend_result, "resistance_levels", None))
        if value > current
    )
    if not supports or not resistances:
        return (
            _simulation_fallback_price_plan(current)
            if simulation_relaxed
            else None,
            simulation_relaxed,
        )
    ideal = max(supports)
    stop = min(supports)
    target = min(resistances)
    if not (0 < stop < current < target):
        return (
            _simulation_fallback_price_plan(current)
            if simulation_relaxed
            else None,
            simulation_relaxed,
        )
    return (round(ideal, 6), round(current, 6), round(stop, 6), round(target, 6)), False


def _simulation_fallback_price_plan(current: float) -> tuple[float, float, float, float]:
    """Provide a deterministic, deliberately simple plan for simulation validation."""

    return (
        round(current * 0.995, 6),
        round(current, 6),
        round(current * 0.97, 6),
        round(current * 1.05, 6),
    )


def _is_non_bearish_trend(trend_result: TrendAnalysisResult) -> bool:
    name = str(getattr(getattr(trend_result, "trend_status", None), "name", "")).upper()
    return name not in {"WEAK_BEAR", "BEAR", "STRONG_BEAR"}


def _reduce_target(decision_context: Mapping[str, Any]) -> Decimal | None:
    try:
        current_weight = Decimal(str(decision_context.get("current_weight")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not Decimal("0") < current_weight <= Decimal("1"):
        return None
    return (current_weight / Decimal("2")).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )


def _current_price(
    trend_result: TrendAnalysisResult | None,
    enhanced_context: Mapping[str, Any],
) -> float | None:
    realtime = enhanced_context.get("realtime")
    today = enhanced_context.get("today")
    return _first_positive(
        (realtime or {}).get("price") if isinstance(realtime, Mapping) else None,
        getattr(trend_result, "current_price", None),
        (today or {}).get("close") if isinstance(today, Mapping) else None,
    )


def _positive_values(*values: Any) -> list[float]:
    result: list[float] = []
    for value in values:
        items = value if isinstance(value, (list, tuple)) else (value,)
        for item in items:
            parsed = _float_or_none(item)
            if parsed is not None and parsed > 0:
                result.append(parsed)
    return result


def _first_positive(*values: Any) -> float | None:
    items = _positive_values(*values)
    return items[0] if items else None


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _text_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _trend_description(trend_result: TrendAnalysisResult | None) -> str:
    if trend_result is None:
        return "趋势数据不足，规则保持观望。"
    return (
        f"趋势={_enum_value(trend_result.trend_status)}；"
        f"评分={normalize_score(trend_result.signal_score)}；"
        f"MA5={trend_result.ma5:.4f}，MA10={trend_result.ma10:.4f}，"
        f"MA20={trend_result.ma20:.4f}；乖离率={trend_result.bias_ma5:.2f}%。"
    )


def _fundamental_description(context: Mapping[str, Any] | None) -> str:
    if not context:
        return "基本面结构化数据不可用；基本面不参与本轮动作升级。"
    status = str(context.get("status") or context.get("data_status") or "available")
    return f"基本面结构化数据状态：{status}；仅作为风险护栏，不替代技术规则。"


def _market_structure_description(context: Mapping[str, Any] | None) -> str:
    if not context:
        return "市场结构数据不可用；规则按安全模式处理。"
    return "市场结构数据已纳入现有确定性护栏。"
