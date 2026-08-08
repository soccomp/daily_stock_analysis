"""Cross-repository canonical M2 runtime snapshot wire proof."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.investment.contracts.portfolio_snapshot import PortfolioSnapshot


ATHENA_ROOT = Path(
    os.environ.get("ATHENA_REPO", Path(__file__).resolve().parents[2] / "athena")
)


@pytest.mark.integration
def test_actual_athena_runtime_projection_round_trips_into_dsa_canonical_snapshot():
    helper = ATHENA_ROOT / "tests/test_trading_spine_runtime_snapshot_m2.py"
    if not helper.is_file():
        pytest.skip("sibling canonical Athena M2 branch is not available")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import json
                import runpy
                from datetime import timedelta

                namespace = runpy.run_path(
                    "tests/test_trading_spine_runtime_snapshot_m2.py"
                )
                clock, api, _controller, ingress = namespace["make_system"]()
                snapshot_a = ingress.capture()
                api.cash = {
                    "available": "899000.00",
                    "nav": "901000.00",
                    "cum_pnl": "0",
                }
                api.positions[0] = {
                    **api.positions[0],
                    "volume": 200,
                    "available": 200,
                    "fpnl": "200.00",
                }
                clock[0] += timedelta(minutes=1)
                snapshot_b = ingress.capture()
                print(json.dumps({
                    "snapshot_a": snapshot_a.to_wire(),
                    "snapshot_b": snapshot_b.to_wire(),
                    "submissions": api.submissions,
                    "cancellations": api.cancellations,
                }, ensure_ascii=False, sort_keys=True))
                """
            ),
        ],
        cwd=ATHENA_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    snapshot_a = PortfolioSnapshot.model_validate_json(
        json.dumps(observed["snapshot_a"], ensure_ascii=False)
    )
    snapshot_b = PortfolioSnapshot.model_validate_json(
        json.dumps(observed["snapshot_b"], ensure_ascii=False)
    )

    assert observed["submissions"] == observed["cancellations"] == 0
    assert snapshot_a.position_for(symbol="600000", market="CN").quantity == 100
    assert snapshot_b.position_for(symbol="600000", market="CN").quantity == 200
    assert snapshot_b.revision == snapshot_a.revision + 1
    assert snapshot_b.supersedes_id == snapshot_a.snapshot_id
    assert snapshot_b.content_hash != snapshot_a.content_hash
    assert snapshot_b.source == "ATHENA_RUNTIME"
    assert snapshot_b.authoritative is snapshot_b.read_only is True
    assert snapshot_b.simulation_only is True
    assert snapshot_b.reconciliation_status == "RECONCILED"
    assert snapshot_b.producer == "ATHENA_M2_RUNTIME_SNAPSHOT_INGRESS"
