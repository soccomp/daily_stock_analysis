"""PALLAS-010 production-shaped price-plan lineage regressions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.investment.contracts.research_trigger import ResearchTrigger
from src.investment.contracts.strategy_evidence import build_pallas008_strategy_evidence
from src.investment.m2.orchestration import DSAAnalysisCompletionRunner
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.storage import DatabaseManager


QUOTE_TIME = datetime(2026, 8, 23, 6, 59, tzinfo=timezone.utc)
FETCH_TIME = datetime(2026, 8, 23, 7, 0, tzinfo=timezone.utc)


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=76,
        trend_prediction="中期上行趋势",
        operation_advice="买入",
        decision_type="buy",
        confidence_level="高",
        action="buy",
        technical_analysis="技术面改善。",
        fundamental_analysis="基本面稳健。",
        analysis_summary="研究结论支持观察性建议。",
        risk_warning="需求转弱。",
        model_used="test/dsa-model",
        dashboard={
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 95,
                    "secondary_buy": 100,
                    "stop_loss": 80,
                    "take_profit": 130,
                }
            }
        },
    )


def _research_trigger() -> ResearchTrigger:
    strategy = build_pallas008_strategy_evidence(
        strategy_id="PALLAS-008-A-SHARE-AUTONOMOUS-V1",
        strategy_version="1.0",
        ranking_method="PALLAS_008_QUANTITATIVE_EVIDENCE",
        ranking_score="0.800000",
        discovery_rank=1,
        ranking_components={
            "momentum_20": "0.800000",
            "momentum_60": "0.800000",
            "trend_strength": "0.800000",
            "liquidity_ratio": "0.800000",
            "market_strength": "0.800000",
        },
        market_strength_raw="0.030000",
        latest_completed_trade_date="2026-08-21",
        decision_cutoff=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
        completion_status="CLOSE_CONFIRMED",
        completion_basis="PRIOR_PROVIDER_RETURNED_SESSION",
        quantitative_input_reference="dsa:test:600519:20260821",
    )
    return ResearchTrigger.build(
        research_trigger_id="research-trigger-price-lineage",
        trigger_type="SCHEDULED_HOLDING_REVIEW",
        trigger_source="single_brain_proposal_handoff",
        symbol="600519",
        market="CN",
        priority=1,
        created_at=QUOTE_TIME,
        effective_at=QUOTE_TIME,
        scheduled_for=QUOTE_TIME,
        dedup_key="holding:600519:20260823",
        policy_version="pallas-004-test-v1",
        evidence_refs=("screening:test:600519",),
        strategy_evidence=strategy,
    )


@pytest.fixture
def lineage_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'pallas-010-price-lineage.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def test_real_completion_snapshot_and_recovery_keep_price_plan_lineage(lineage_db):
    quote = UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.TUSHARE,
        fetched_at=FETCH_TIME.isoformat(),
        provider_timestamp=QUOTE_TIME.isoformat(),
        price=100.0,
    )
    snapshot_pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    snapshot_pipeline.analysis_skills = None

    def factory(**_kwargs):
        class Pipeline:
            def process_single_stock(self, symbol, **kwargs):
                result = _analysis_result()
                result.code = symbol
                snapshot = snapshot_pipeline._build_context_snapshot(
                    enhanced_context={
                        "code": symbol,
                        "today": {"close": quote.price},
                    },
                    news_content=None,
                    realtime_quote=quote,
                    chip_data=None,
                )
                assert snapshot["price_input_lineage"] == {
                    "lineage_role": "RESEARCH_OBSERVATION",
                    "input_kind": "REALTIME_QUOTE",
                    "symbol": "600519",
                    "provider": "tushare",
                    "source_reference": (
                        "dsa:realtime-quote:600519:tushare:"
                        "2026-08-23T06:59:00+00:00"
                    ),
                    "source_event_time": "2026-08-23T06:59:00+00:00",
                    "retrieved_at": "2026-08-23T07:00:00+00:00",
                    "observed_at": "2026-08-23T07:00:00+00:00",
                    "price": 100.0,
                    "quote_identity": {
                        "symbol": "600519",
                        "provider": "tushare",
                        "provider_timestamp": "2026-08-23T06:59:00+00:00",
                        "price": 100.0,
                    },
                    "completion_status": "INTRADAY_OBSERVED",
                }
                source_id = lineage_db.save_analysis_history(
                    result=result,
                    query_id=kwargs["analysis_query_id"],
                    report_type="simple",
                    news_content=None,
                    context_snapshot=snapshot,
                    save_snapshot=True,
                )
                assert source_id > 0
                return result

        return Pipeline()

    runner = DSAAnalysisCompletionRunner(
        config=object(),
        db_manager=lineage_db,
        pipeline_factory=factory,
    )
    first = runner.complete(
        cycle_id="cycle-price-lineage",
        symbol="600519",
        query_id="query-price-lineage",
        current_time=FETCH_TIME,
    )
    recovered = runner.complete(
        cycle_id="cycle-price-lineage",
        symbol="600519",
        query_id="query-price-lineage",
        current_time=FETCH_TIME,
    )

    assert first.recovered is False
    assert recovered.recovered is True
    assert first.context_snapshot == recovered.context_snapshot

    trigger = _research_trigger()
    first_artifacts = InvestmentProposalBuilder(
        clock=lambda: first.completed_at,
    ).build(
        result=first.result,
        context_snapshot=first.context_snapshot,
        source_report_id=first.source_report_id,
        cycle_id="cycle-price-lineage",
        trigger_source="single_brain_proposal_handoff",
        research_trigger=trigger,
    )
    recovered_artifacts = InvestmentProposalBuilder(
        clock=lambda: recovered.completed_at,
    ).build(
        result=recovered.result,
        context_snapshot=recovered.context_snapshot,
        source_report_id=recovered.source_report_id,
        cycle_id="cycle-price-lineage",
        trigger_source="single_brain_proposal_handoff",
        research_trigger=trigger,
    )

    first_price_evidence = next(
        item for item in first_artifacts.research_bundle.data_evidence
        if item.data_class == "PRICE_PLAN"
    )
    recovered_price_evidence = next(
        item for item in recovered_artifacts.research_bundle.data_evidence
        if item.data_class == "PRICE_PLAN"
    )
    assert first_price_evidence.freshness_status == "FRESH"
    assert first_price_evidence.availability_status == "AVAILABLE"
    assert first_price_evidence.source_event_time.isoformat() == QUOTE_TIME.isoformat()
    assert first_price_evidence.retrieved_at.isoformat() == FETCH_TIME.isoformat()
    assert first_price_evidence.source_reference.startswith(
        "dsa:realtime-quote:600519:tushare:"
    )
    assert first_price_evidence.content_hash == recovered_price_evidence.content_hash
    assert first_artifacts.proposal.content_hash == recovered_artifacts.proposal.content_hash
