"""Canonical Pallas Screening -> ProposalHandoff evidence."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.m2.screening_candidates import ScreeningCandidate
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from tests.test_investment_proposal_issue_9 import NOW, _ack, _result
from tests.test_m2_screening_candidates import _snapshot_many


class _ScreeningSource:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = []

    def latest(self, *, max_candidates, max_age):
        self.calls.append((max_candidates, max_age))
        return self._candidates[:max_candidates]


class _Runner:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        result = _result("hold")
        result.code = kwargs["symbol"]
        return AnalysisCompletion(result, {}, 11, False, NOW)


class _Publisher:
    def __init__(self):
        self.proposals = []

    def publish(self, proposal):
        self.proposals.append(proposal)
        return _ack(proposal, "NO_ACTION")


class _SnapshotSource:
    def __init__(self, holdings):
        self._holdings = holdings

    def capture_snapshot(self):
        return _snapshot_many(*self._holdings)


def test_canonical_proposal_handoff_preserves_screening_lineage():
    holdings = (
        "600519", "600036", "601318", "000858", "000651", "600030", "601166",
        "600887", "601988", "601288", "000001", "600000", "601398", "600028",
    )
    screening_candidates = [
        ScreeningCandidate(
            symbol=symbol,
            name=f"candidate-{index}",
            screening_run_id="screening-run-1",
            strategy="capital_heat",
            rank=index,
            screen_score=80.0 - index,
            score=81.0 - index,
            selected_at=NOW.isoformat(),
        )
        for index, symbol in enumerate(("300274", "600362", "600111"), start=1)
    ]
    config = SimpleNamespace(
        single_brain_m2_enabled=True,
        single_brain_m2_interval_minutes=60,
        single_brain_m2_symbols=(),
        single_brain_m2_max_symbols=6,
        single_brain_m2_holdings_limit=3,
        single_brain_m2_screening_enabled=True,
        single_brain_m2_screening_max_candidates=3,
        single_brain_m2_screening_max_age_hours=72,
    )
    runner = _Runner()
    screening_source = _ScreeningSource(screening_candidates)
    publisher = _Publisher()
    service = ProposalHandoffLoopService(
        config=config,
        analysis_runner=runner,
        publisher=publisher,
        snapshot_source=_SnapshotSource(holdings),
        screening_candidate_source=screening_source,
        clock=lambda: NOW,
    )
    result = service.run_cycle(scheduled_for=NOW)

    assert result.status == "COMPLETED"
    assert result.researched_symbols == (
        "600519:HOLDING", "600036:HOLDING", "601318:HOLDING",
        "300274:SCREENING", "600362:SCREENING", "600111:SCREENING",
    )
    assert len(runner.calls) == len(publisher.proposals) == 6
    assert all(item.acknowledgement_state == "ACCEPTED" for item in result.acknowledgements)
    assert all(item.lifecycle_state == "NO_ACTION" for item in result.acknowledgements)
    assert screening_source.calls == [(3, timedelta(hours=72))]

    screening_proposals = [
        item for item in publisher.proposals
        if item.candidate_provenance is not None
        and item.candidate_provenance.candidate_source == "SCREENING"
    ]
    assert len(screening_proposals) == 3
    for proposal in screening_proposals:
        provenance = proposal.candidate_provenance
        assert provenance is not None
        assert provenance.screening_run_id == "screening-run-1"
        assert provenance.screening_strategy == "capital_heat"
        assert provenance.screening_rank in {1, 2, 3}
        assert provenance.screening_score is not None
        assert provenance.screening_selected_at == NOW
