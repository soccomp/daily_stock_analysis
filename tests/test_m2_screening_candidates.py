"""Gate 2: screening candidate adapter + M2 research-object selection proofs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.config import Config
from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot
from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource
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
