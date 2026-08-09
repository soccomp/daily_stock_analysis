import inspect
from urllib.error import URLError

import pytest

from src.investment.integration.execution_transport import (
    CanonicalHttpAthenaExecutionTransport,
    ExecutionTransportUncertain,
)
from src.investment.execution_projection.mandate import ExecutionMandateProjector
from src.investment.shadow_wiring import InvestmentShadowWiringService
from tests.test_investment_shadow_wiring_p1a import (
    NOW,
    _analysis_result,
    _policy,
    _snapshot,
)


def _mandate():
    artifacts = InvestmentShadowWiringService(clock=lambda: NOW).build_from_analysis(
        result=_analysis_result(),
        context_snapshot={"data_quality": {"level": "good"}},
        source_report_id=42,
        trace_id="trace:m3:transport",
        trigger_source="single_brain_m3_simulation_execution",
        portfolio_snapshot=_snapshot(),
        risk_policy=_policy(),
    )
    return ExecutionMandateProjector.project(artifacts.investment_decision)


@pytest.mark.parametrize(
    "url",
    (
        "https://127.0.0.1:18761/v1/trading-spine/execute",
        "http://192.0.2.1:18761/v1/trading-spine/execute",
        "http://127.0.0.1:18761/v1/simulation/deploy",
        "http://127.0.0.1:18761/v1/trading-spine/execute?retry=true",
    ),
)
def test_m3_transport_accepts_only_exact_loopback_canonical_endpoint(url):
    with pytest.raises(ValueError, match="exact loopback"):
        CanonicalHttpAthenaExecutionTransport(url=url)


def test_m3_transport_makes_one_attempt_and_never_retries_uncertain_submission():
    calls = []

    def opener(*args, **kwargs):
        calls.append((args, kwargs))
        raise URLError("connection outcome unknown")

    transport = CanonicalHttpAthenaExecutionTransport(
        url="http://127.0.0.1:18761/v1/trading-spine/execute",
        opener=opener,
    )

    with pytest.raises(ExecutionTransportUncertain, match="reconciliation is required"):
        transport.execute(_mandate(), _snapshot())

    assert len(calls) == 1


def test_m3_reconciliation_transport_has_no_mandate_or_snapshot_override():
    parameters = tuple(
        inspect.signature(CanonicalHttpAthenaExecutionTransport.reconcile).parameters
    )
    assert parameters == ("self", "mandate")
