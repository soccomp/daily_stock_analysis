"""Gate 2: screening candidate adapter + M2 research-object selection proofs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.config import Config
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.m2.screening_candidates import (
    DatabaseScreeningCandidateSource,
    screening_quality_failure,
)
from src.investment.m2.selection import select_m2_research_objects

from tests.test_investment_shadow_wiring_p1a import Position, _snapshot


def _config(*, symbols=(), max_symbols=10, holdings_limit=10):
    return Config(
        single_brain_m2_symbols=list(symbols),
        single_brain_m2_max_symbols=max_symbols,
        single_brain_m2_holdings_limit=holdings_limit,
    )


def _screening_candidates(*symbols):
    return [
        {
            "symbol": symbol,
            "source": "SCREENING",
            "screening_run_id": "run-1",
            "strategy": "capital_heat",
            "rank": idx + 1,
            "screening_score": 80.0 - idx,
            "score": 81.0 - idx,
            "selected_at": "2026-08-18T01:00:00+00:00",
        }
        for idx, symbol in enumerate(symbols)
    ]


def _snapshot_many(*symbols):
    """Build a portfolio snapshot holding one CN position per given symbol."""
    as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
    positions = tuple(
        Position(
            symbol=sym,
            market="CN",
            quantity=100,
            available_quantity=100,
            avg_cost=Decimal("10.00"),
            last_price=Decimal("12.00"),
            market_value=Decimal("1200.00"),
            unrealized_pnl=Decimal("200.00"),
            price_as_of=as_of,
            price_source="ATHENA_DECIMAL_SIM",
        )
        for sym in symbols
    )
    return PortfolioSnapshot.build(
        snapshot_id="snapshot-many",
        trace_id="athena-snapshot-trace-many",
        created_at=as_of,
        producer="ATHENA_SIMULATION_RECONCILIATION",
        account_id="simulation-account-1",
        broker="ATHENA_DECIMAL_SIM",
        account_mode="SIMULATION",
        as_of=as_of,
        revision=1,
        currency="CNY",
        equity=Decimal("1000000.00"),
        cash=Decimal("400000.00"),
        available_cash=Decimal("400000.00"),
        reserved_cash=Decimal("0.00"),
        positions=positions,
        active_orders=(),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("2400.00"),
        reconciliation_status="RECONCILED",
        data_quality="HIGH",
        limitations=(),
        broker_snapshot_ref="athena-sim:snapshot-many",
    )


# --- selection ordering / source lineage ----------------------------------

def test_screening_candidates_are_injected_with_source_lineage():
    snapshot = _snapshot()  # holds 600519
    config = _config(symbols=(), max_symbols=10, holdings_limit=10)
    scope = select_m2_research_objects(
        config=config,
        snapshot=snapshot,
        screening_candidates=_screening_candidates("300274", "600362"),
    )
    by_symbol = {item["symbol"]: item for item in scope}
    assert "600519" in by_symbol  # holding still first
    assert by_symbol["300274"]["source"] == "SCREENING"
    assert by_symbol["300274"]["screening_run_id"] == "run-1"
    assert by_symbol["300274"]["strategy"] == "capital_heat"
    assert by_symbol["300274"]["rank"] == 1
    # holdings before screening
    assert scope[0]["symbol"] == "600519"


def test_exchange_qualified_portfolio_symbols_are_selected_as_cn_holdings():
    """GM/Tushare SHSE/SZSE wire symbols must not disappear from the scope."""
    snapshot = _snapshot_many("SHSE.600533", "SZSE.000977")
    config = _config(symbols=(), max_symbols=2, holdings_limit=2)

    scope = select_m2_research_objects(config=config, snapshot=snapshot)

    assert [item["symbol"] for item in scope] == ["600533", "000977"]
    assert all(item["source"] == "HOLDING" for item in scope)


def test_screening_candidate_that_is_also_holding_is_deduped():
    snapshot = _snapshot()  # holds 600519
    config = _config(symbols=(), max_symbols=10, holdings_limit=10)
    scope = select_m2_research_objects(
        config=config,
        snapshot=snapshot,
        screening_candidates=_screening_candidates("600519", "300274"),
    )
    symbols = [item["symbol"] for item in scope]
    assert symbols.count("600519") == 1
    assert symbols == ["600519", "300274"]


def test_allowlist_is_manual_override_only_when_not_in_screening():
    snapshot = _snapshot()
    # allowlist has 000977 (not a holding, not in screening) -> appended as override
    config = _config(symbols=("000977",), max_symbols=10, holdings_limit=10)
    scope = select_m2_research_objects(
        config=config,
        snapshot=snapshot,
        screening_candidates=_screening_candidates("300274"),
    )
    symbols = [item["symbol"] for item in scope]
    assert "000977" in symbols
    assert {item["symbol"]: item["source"] for item in scope}["000977"] == "ALLOWLIST"


def test_max_symbols_caps_total_scope():
    snapshot = _snapshot()
    config = _config(symbols=(), max_symbols=2, holdings_limit=10)
    scope = select_m2_research_objects(
        config=config,
        snapshot=snapshot,
        screening_candidates=_screening_candidates("300274", "600362", "600111"),
    )
    assert len(scope) == 2


def test_holdings_limit_3_plus_screening_3_with_max_symbols_6():
    """Phase 2B production scenario: 14 holdings, holdings_limit=3,
    3 screening candidates, max_symbols=6 -> exactly 3 holdings + 3 screening."""
    holdings = (
        "600519", "600036", "601318", "000858", "000651", "600030", "601166",
        "600887", "601988", "601288", "000001", "600000", "601398", "600028",
    )
    assert len(holdings) == 14
    snapshot = _snapshot_many(*holdings)
    config = _config(symbols=(), max_symbols=6, holdings_limit=3)
    scope = select_m2_research_objects(
        config=config,
        snapshot=snapshot,
        screening_candidates=_screening_candidates("300274", "600362", "600111"),
    )

    # 总数为 6，且不截断
    assert len(scope) == 6

    holdings_part = [item for item in scope if item["source"] == "HOLDING"]
    screening_part = [item for item in scope if item["source"] == "SCREENING"]

    # 恰好 3 持仓 + 3 选股候选
    assert len(holdings_part) == 3
    assert len(screening_part) == 3

    # 持仓取前 3 只（14 只里按顺序取，被 holdings_limit=3 截断）
    assert [item["symbol"] for item in holdings_part] == ["600519", "600036", "601318"]
    # 选股候选按序注入
    assert [item["symbol"] for item in screening_part] == ["300274", "600362", "600111"]

    # 顺序：持仓在前，选股候选在后
    assert scope[0]["source"] == "HOLDING"
    assert scope[2]["source"] == "HOLDING"
    assert scope[3]["source"] == "SCREENING"
    assert scope[5]["source"] == "SCREENING"


# --- database candidate source --------------------------------------------

class _StubDB:
    def __init__(self, run):
        self.run = run

    def list_screening_runs(self, *, limit=1, strategy=None, market=None):
        return [self.run]

    def get_screening_run(self, run_id):
        return self.run


def _run(created_at, candidates):
    return {
        "run_id": "run-1",
        "strategy": "capital_heat",
        "market": "cn",
        "created_at": created_at.isoformat(),
        "result": {"candidates": candidates},
    }


def test_source_projects_fresh_candidates():
    db = _StubDB(_run(
        datetime.now(timezone.utc) - timedelta(hours=1),
        [
            {"code": "300274", "name": "阳光电源", "rank": 1, "screen_score": 74.4, "score": 81.2},
            {"code": "600362", "name": "江西铜业", "rank": 2, "screen_score": 71.1, "score": 76.1},
        ],
    ))
    src = DatabaseScreeningCandidateSource(db)
    out = src.latest(max_candidates=3, max_age=timedelta(hours=72))
    assert [c.symbol for c in out] == ["300274", "600362"]
    assert out[0].as_scope()["source"] == "SCREENING"
    assert out[0].as_scope()["screening_run_id"] == "run-1"
    assert out[0].as_scope()["strategy"] == "capital_heat"


def test_source_recovers_candidate_by_persisted_run_and_symbol():
    db = _StubDB(_run(
        datetime.now(timezone.utc) - timedelta(hours=1),
        [{"code": "300274", "name": "阳光电源", "rank": 1, "screen_score": 74.4, "score": 81.2}],
    ))
    candidate = DatabaseScreeningCandidateSource(db).by_run(
        screening_run_id="run-1",
        symbol="300274",
    )
    assert candidate is not None
    assert candidate.as_scope() == {
        "symbol": "300274",
        "source": "SCREENING",
        "screening_run_id": "run-1",
        "strategy": "capital_heat",
        "rank": 1,
        "screening_score": 74.4,
        "score": 81.2,
        "selected_at": candidate.selected_at,
    }


def test_source_skips_stale_run():
    db = _StubDB(_run(
        datetime.now(timezone.utc) - timedelta(days=30),
        [{"code": "300274", "rank": 1}],
    ))
    src = DatabaseScreeningCandidateSource(db)
    out = src.latest(max_candidates=3, max_age=timedelta(hours=72))
    assert out == []


def test_source_caps_and_dedups():
    db = _StubDB(_run(
        datetime.now(timezone.utc) - timedelta(hours=1),
        [
            {"code": "300274", "rank": 1},
            {"code": "300274", "rank": 2},
            {"code": "600362", "rank": 3},
            {"code": "600111", "rank": 4},
        ],
    ))
    src = DatabaseScreeningCandidateSource(db)
    out = src.latest(max_candidates=2, max_age=timedelta(hours=72))
    assert [c.symbol for c in out] == ["300274", "600362"]


def test_quality_gate_accepts_explicit_deterministic_rank_fallback():
    assert screening_quality_failure({
        "source_errors": [],
        "warnings": [
            "DSA provider context applied 3 of 3 candidates",
            "LLM ranking failed: fell back to screen_score",
        ],
        "degradation": [],
    }) is None


def test_quality_gate_rejects_unclassified_provider_degradation():
    reason = screening_quality_failure({
        "source_errors": [],
        "warnings": [],
        "degradation": ["snapshot source fallback: provider unavailable"],
    })
    assert reason == "screening quality is degraded: snapshot source fallback: provider unavailable"
