# Single Brain P0.1 Implementation Status — DSA

**Status date:** 2026-08-08

**Repository role:** Research and sole Investment Decision Brain

**Lifecycle state:** P0 implemented and verified; P0.1 governance closeout pending PR review

**Normative architecture:** [Single Brain Architecture Constitution](SINGLE_BRAIN_CONSTITUTION.md)

## Delivered scope

DSA now implements the Brain half of the minimal one-account, one-stock, one BUY/ADD, LIMIT, simulation-only vertical slice.

- Six strict, versioned, immutable canonical contracts with stable canonical JSON, decimal-string semantics, aware timestamps, provenance, stable IDs, and content hashes.
- A `ResearchBundle` adapter that keeps research descriptive and carries no final allocation fields.
- A deterministic `InvestmentDecisionEngine` that consumes exact `ResearchBundle`, authoritative `PortfolioSnapshot`, and explicit `RiskPolicy` inputs.
- Final target and delta quantity calculation inside DSA, including the P0 position, total exposure, minimum cash, per-trade risk, concurrent-position, and lot constraints.
- A deterministic `ExecutionMandate` projector with no quantity override parameter.
- A legacy-compatible `DecisionSignal` UI/API projection from the same `InvestmentDecision`; it is not an execution protocol.
- Architecture tests that protect DSA Research and Decision from broker/execution dependencies.
- A cross-repository subprocess integration test that proves DSA ADD 200 becomes Athena exact submit 200 and reconciles Snapshot B.

The existing DSA agent, screening, portfolio, API, and Web flows remain in place. This is an additive P0 path; DSA's existing local portfolio service is not used as authoritative truth for an Athena-integrated account.

## Implementation map

| Responsibility | Location |
| --- | --- |
| Contract envelope, canonical JSON, hash and immutability | `src/investment/contracts/base.py` |
| `ResearchBundle` | `src/investment/contracts/research_bundle.py` |
| `PortfolioSnapshot` | `src/investment/contracts/portfolio_snapshot.py` |
| `RiskPolicy` | `src/investment/contracts/risk_policy.py` |
| `InvestmentDecision` | `src/investment/contracts/investment_decision.py` |
| `ExecutionMandate` | `src/investment/contracts/execution_mandate.py` |
| `ExecutionResult` | `src/investment/contracts/execution_result.py` |
| DSA research adaptation | `src/investment/research/adapter.py` |
| Final quantity and capital allocation | `src/investment/decision/engine.py` |
| Mandate projection | `src/investment/execution_projection/mandate.py` |
| DecisionSignal projection | `src/investment/execution_projection/decision_signal.py` |

## Authority proof

- Final quantity is computed only by `InvestmentDecisionEngine` and stored in `InvestmentDecision`.
- `ExecutionMandateProjector.project()` receives no quantity argument; it binds the mandate quantity to `decision.delta_quantity`.
- The decision binds the exact research IDs, portfolio snapshot ID/hash, policy ID/version, cycle ID, and model provenance.
- Athena `PortfolioSnapshot` is consumed as immutable, authoritative, read-only account truth.

## Verification evidence

Final implementation validation completed before this documentation-only closeout:

- Full DSA suite: `/private/tmp/dsa-athena-p0-ci/bin/python -m pytest -q` — **5777 passed, 2 skipped**.
- Focused `test_investment_p0.py`, architecture, and cross-repository suite — **35 passed**.
- Cross-repository invariant: `decision.delta_quantity == mandate.quantity == execution.requested_quantity == execution.submitted_quantity == 200`; reconciled position equals Snapshot A quantity plus observed fill.
- Critical lint and diff checks passed.

## Compatibility

- No existing public API was removed or changed.
- Existing `DecisionSignal` remains available as a projection.
- Existing DSA research/risk/orchestration flows remain available and are not silently routed into execution.
- No live-trading path or broker SDK dependency was added to DSA.

## Publication and upstream policy

- The canonical P0 implementation branch and PR live in `soccomp/daily_stock_analysis`.
- No P0 PR is opened automatically against `ZhuLinsen/daily_stock_analysis`.
- The current P0 implementation commit is additive and isolated, but it is not demonstrably generic as-is: its canonical contracts, authoritative snapshot rules, execution mandate lineage, simulation-only restrictions, and cross-repository test intentionally encode the DSA/Athena boundary.
- The governance commit is system-specific and must not be upstreamed independently without upstream agreement on the Single Brain constitution.
- A future upstream proposal should be a separately authored extraction. The most plausible candidates are the generic immutable canonical-JSON/hash contract utility and the DecisionSignal projection pattern, but neither is a safe direct cherry-pick today because both currently depend on P0-specific contracts and semantics.

## Intentionally out of P0

- Multiple simultaneous symbols or decision-cycle portfolio allocation.
- SELL/REDUCE execution, complex conditional stops, and take-profit automation.
- Live trading, message queues, service decomposition, or repository merger.
- Full Decision Scorecard UI and broad DSA Web UI integration.
- Retirement of legacy DSA or Athena investment paths.

## Canonical next-phase handoff

Future DSA phases must update this file in the implementation PR. Any cross-repository contract or authority change requires a coordinated Athena PR, cross-links between the two PRs, explicit wire-compatibility evidence, and matching constitutional amendments when the authority boundary changes.
