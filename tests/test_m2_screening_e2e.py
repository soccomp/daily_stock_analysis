"""Gate 4.1: end-to-end proof that a screening candidate flows into M2 research.

The canonical investment path starts at DSA screening.  This test wires a
screening candidate source into the M2 shadow loop and proves the candidate is
actually researched (source=SCREENING), not just present in the selection
projection.
"""

from __future__ import annotations

import pytest

from src.config import Config
from src.investment.m2.orchestration import M2ShadowLoopService
from src.investment.m2.repository import M2OperationalRepository
from src.investment.m2.screening_candidates import ScreeningCandidate
from src.services.decision_scorecard_service import DecisionScorecardService
from src.storage import DatabaseManager

from tests.test_investment_shadow_wiring_p1a import NOW, _analysis_result, _policy, _snapshot
from tests.test_single_brain_m2_shadow_loop import (
    _AnalysisRunner,
    _PolicySource,
    _SnapshotSource,
)


class _ScreeningSource:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = []

    def latest(self, *, max_candidates, max_age):
        self.calls.append((max_candidates, max_age))
        return self._candidates[:max_candidates]


@pytest.fixture
def m2_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'm2.db'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def _config(enabled=True):
    config = Config()
    config.single_brain_m2_enabled = enabled
    config.single_brain_m2_account_id = "simulation-account-1"
    config.single_brain_m2_symbols = []  # no manual override
    config.single_brain_m2_max_symbols = 5
    config.single_brain_m2_holdings_limit = 5
    config.single_brain_m2_interval_minutes = 60
    config.single_brain_m2_screening_enabled = True
    config.single_brain_m2_screening_max_candidates = 3
    config.single_brain_m2_screening_max_age_hours = 72
    return config


def _screening_candidate(symbol="300274"):
    return ScreeningCandidate(
        symbol=symbol,
        name="阳光电源",
        screening_run_id="run-1",
        strategy="capital_heat",
        rank=1,
        screen_score=74.4,
        score=81.2,
        selected_at=NOW.isoformat(),
    )


def test_screening_candidate_is_researched_by_m2_loop(m2_db):
    runner = _AnalysisRunner()
    screening_source = _ScreeningSource([_screening_candidate("300274")])
    service = M2ShadowLoopService(
        config=_config(),
        snapshot_source=_SnapshotSource(_snapshot()),  # holds 600519, not 300274
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner,
        lineage_store=DecisionScorecardService(db_manager=m2_db),
        repository=M2OperationalRepository(m2_db),
        screening_candidate_source=screening_source,
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert screening_source.calls  # the adapter was consulted
    researched = {kwargs["symbol"] for kwargs in runner.calls}
    assert "300274" in researched  # the screening candidate was actually researched
    assert "600519" in researched  # holding still researched


def test_screening_source_failure_falls_back_to_holdings_only(m2_db):
    class _ExplodingSource:
        def latest(self, *, max_candidates, max_age):
            raise RuntimeError("screening db unavailable")

    runner = _AnalysisRunner()
    service = M2ShadowLoopService(
        config=_config(),
        snapshot_source=_SnapshotSource(_snapshot()),
        policy_source=_PolicySource(_policy()),
        analysis_runner=runner,
        lineage_store=DecisionScorecardService(db_manager=m2_db),
        repository=M2OperationalRepository(m2_db),
        screening_candidate_source=_ExplodingSource(),
        clock=lambda: NOW,
    )

    result = service.run_cycle(scheduled_for=NOW)

    # The loop must not fail closed because screening scope is best-effort.
    assert result.status == "COMPLETED"
    researched = {kwargs["symbol"] for kwargs in runner.calls}
    assert "600519" in researched
