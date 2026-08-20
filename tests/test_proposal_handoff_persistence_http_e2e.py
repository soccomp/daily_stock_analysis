"""Pallas evidence upgrade: real DSA persistence through isolated Athena ACK."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.request import urlopen

import pytest

from src.investment.contracts.investment_proposal import InvestmentProposal
from src.investment.m2.orchestration import AnalysisCompletion
from src.investment.m2.screening_candidates import DatabaseScreeningCandidateSource
from src.investment.proposal.builder import InvestmentProposalBuilder
from src.investment.proposal.orchestration import ProposalHandoffLoopService
from src.investment.proposal.transport import CanonicalHttpInvestmentProposalPublisher
from src.storage import DatabaseManager
from tests.test_investment_proposal_issue_9 import _result
from tests.test_m2_screening_candidates import _snapshot_many


ATHENA_SERVER = r'''
import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

from src.command_center.webapp import handler
from src.investment_authority.service import InvestmentAuthorityService


class IsolatedAthenaIntake:
    def __init__(self):
        self.authority = InvestmentAuthorityService(
            journal_path=sys.argv[1],
            clock=lambda: datetime.now(timezone.utc),
        )

    def health(self):
        return {"service": "READY", "runtime_projection": "READ_ONLY", "read_only": True}

    def submit_investment_proposal(self, raw):
        return self.authority.accept_json(raw)

    def investment_proposal_acknowledgement(self, proposal_id):
        acknowledgement = self.authority.acknowledgement(proposal_id)
        if acknowledgement is None:
            raise ValueError("investment proposal acknowledgement not found")
        return acknowledgement


server = ThreadingHTTPServer(("127.0.0.1", 0), handler(IsolatedAthenaIntake()))
print(server.server_port, flush=True)
server.serve_forever()
'''


class _DeterministicAnalysisRunner:
    def __init__(self, completed_at: datetime):
        self._completed_at = completed_at

    def complete(self, **kwargs):
        result = _result("hold")
        result.code = kwargs["symbol"]
        return AnalysisCompletion(
            result=result,
            context_snapshot={"source": "pallas-evidence-upgrade"},
            source_report_id=11,
            recovered=False,
            completed_at=self._completed_at,
        )


class _SnapshotSource:
    def capture_snapshot(self):
        return _snapshot_many()


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@contextmanager
def _isolated_athena_intake(tmp_path: Path) -> Iterator[str]:
    default_root = Path(__file__).resolve().parents[2] / "pallas-athena-recovery"
    athena_root = Path(
        os.environ.get("PALLAS_ATHENA_RECOVERY_ROOT", str(default_root))
    ).resolve()
    athena_python = Path(
        os.environ.get(
            "PALLAS_ATHENA_PYTHON",
            "/Users/m5air/Documents/Athena/.venv/bin/python",
        )
    )
    if not athena_root.is_dir():
        pytest.fail(f"isolated Athena recovery root is missing: {athena_root}")
    if not athena_python.is_file():
        pytest.fail(f"isolated Athena Python is missing: {athena_python}")

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(athena_root)
    journal_path = tmp_path / "athena-investment-authority.jsonl"
    process = subprocess.Popen(
        [str(athena_python), "-u", "-c", ATHENA_SERVER, str(journal_path)],
        cwd=athena_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    port_line = process.stdout.readline().strip()
    if not port_line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        process.terminate()
        process.wait(timeout=5)
        pytest.fail(f"isolated Athena intake did not start: {stderr}")
    try:
        yield f"http://127.0.0.1:{int(port_line)}/api/investment-proposals"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture
def persisted_screening_db(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screening-evidence.sqlite'}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()


def test_persistence_backed_screening_to_isolated_athena_ack(
    persisted_screening_db,
    tmp_path,
):
    db = persisted_screening_db
    screening_run_id = "screening-run-real-db-1"
    candidate_selected_at = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "run_id": screening_run_id,
        "strategy": "capital_heat",
        "market": "cn",
        "candidate_count": 1,
        "candidates": [{
            "code": "300274",
            "name": "阳光电源",
            "rank": 1,
            "screen_score": 88.5,
            "score": 92.1,
            "selected_at": candidate_selected_at.isoformat(),
        }],
    }
    assert db.save_screening_run(payload) == 1
    persisted = db.get_screening_run(screening_run_id)
    assert persisted is not None
    assert persisted["result"]["candidates"][0]["code"] == "300274"
    assert persisted["result"]["candidates"][0]["selected_at"] == candidate_selected_at.isoformat()

    screening_source = DatabaseScreeningCandidateSource(db)
    candidates = screening_source.latest(
        max_candidates=3,
        max_age=timedelta(hours=72),
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    scope = candidate.as_scope()
    assert scope["symbol"] == "300274"
    assert scope["screening_run_id"] == screening_run_id
    assert scope["strategy"] == "capital_heat"
    assert scope["rank"] == 1
    assert scope["screening_score"] == 88.5
    assert _aware(scope["selected_at"]) == _aware(persisted["created_at"])

    runtime_now = datetime.now(timezone.utc).replace(microsecond=0)
    config = type("EvidenceConfig", (), {
        "single_brain_m2_enabled": True,
        "single_brain_m2_interval_minutes": 60,
        "single_brain_m2_symbols": (),
        "single_brain_m2_max_symbols": 1,
        "single_brain_m2_holdings_limit": 0,
        "single_brain_m2_screening_enabled": True,
        "single_brain_m2_screening_max_candidates": 3,
        "single_brain_m2_screening_max_age_hours": 72,
    })()
    captured_artifacts = []
    real_build = InvestmentProposalBuilder.build

    def build_and_capture(builder, **kwargs):
        artifacts = real_build(builder, **kwargs)
        captured_artifacts.append(artifacts)
        return artifacts

    with _isolated_athena_intake(tmp_path) as endpoint:
        publisher = CanonicalHttpInvestmentProposalPublisher(url=endpoint)
        service = ProposalHandoffLoopService(
            config=config,
            analysis_runner=_DeterministicAnalysisRunner(runtime_now),
            publisher=publisher,
            snapshot_source=_SnapshotSource(),
            screening_candidate_source=screening_source,
            clock=lambda: runtime_now,
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(InvestmentProposalBuilder, "build", build_and_capture)
            result = service.run_cycle(scheduled_for=runtime_now)

        assert result.status == "COMPLETED", result.blocked_reasons
        assert result.researched_symbols == ("300274:SCREENING",)
        assert len(captured_artifacts) == 1
        artifacts = captured_artifacts[0]
        assert isinstance(artifacts.proposal, InvestmentProposal)
        assert artifacts.research_bundle.candidate_provenance is not None
        assert artifacts.proposal.candidate_provenance is not None
        assert artifacts.research_bundle.candidate_provenance == artifacts.proposal.candidate_provenance
        provenance = artifacts.proposal.candidate_provenance
        assert provenance.candidate_source == "SCREENING"
        assert provenance.screening_run_id == screening_run_id
        assert provenance.screening_strategy == "capital_heat"
        assert provenance.screening_rank == 1
        assert provenance.screening_score == 88.5

        assert len(result.acknowledgements) == 1
        acknowledgement = result.acknowledgements[0]
        assert acknowledgement.proposal_id == artifacts.proposal.proposal_id
        assert acknowledgement.proposal_hash == artifacts.proposal.content_hash
        assert acknowledgement.acknowledgement_state == "ACCEPTED"
        with urlopen(
            f"{endpoint}/{acknowledgement.proposal_id}/ack",
            timeout=2,
        ) as response:
            lookup = json.loads(response.read())
        assert lookup["acknowledgement_id"] == acknowledgement.acknowledgement_id
        assert lookup["acknowledgement_state"] == "ACCEPTED"
