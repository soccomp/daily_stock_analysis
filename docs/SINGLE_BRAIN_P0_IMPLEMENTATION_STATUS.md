# Single Brain P0/P1A Implementation Status — DSA

**Status date:** 2026-08-08

**Repository role:** Research and sole Investment Decision Brain

**Lifecycle state:** P0 and P1A verified; P1B Simulation Canary and P1C Single Decision Scorecard implemented on the P1 Mission branch

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

## P1A Shadow Wiring

P1A adds one internal, default-off hook after a real legacy or Agent analysis result has been saved to analysis history.

- `DSA_INVESTMENT_SHADOW_ENABLED=false` by default.
- The hook adapts the completed `AnalysisResult` into a `ResearchBundle`; it does not use fixture-only research or a second research engine.
- It accepts only programmatically injected canonical `PortfolioSnapshot` and `RiskPolicy` objects. It has no Athena runtime, broker, HTTP, queue, scheduler, or execution dependency.
- It produces one `InvestmentDecision` and one internal `DecisionSignal` projection. P1A deliberately does not create an `ExecutionMandate`.
- Its deterministic sizing input is now the risk-budget-derived target used by P1B; `max_single_position_weight` remains a cap rather than an investment target.
- Shadow artifacts stay on a private runtime-only result attribute. They are not persisted and are absent from `AnalysisResult.to_dict()`, public APIs, UI, notifications, and existing DecisionSignal storage.
- Missing, invalid, future, stale (older than five minutes), unreconciled, or non-simulation portfolio truth and missing/invalid/expired policy inputs fail closed with no shadow decision artifacts.
- P1A remains CN-equity BUY/ADD/HOLD research shadowing only and introduces no trading capability.

## P1B Simulation Canary

- `DSA_INVESTMENT_CANARY_ENABLED=false` is a separate default-off switch; P1A enablement never enables P1B.
- DSA Brain computes `risk_budget_per_trade / stop_loss_fraction` with Decimal semantics and caps the target by `max_single_position_weight`. An existing position at or above that target produces HOLD without mandate projection or transport execution.
- The real legacy and Agent analysis-completion hooks can run one allowlisted canary only when an explicit account, symbol allowlist, canonical RiskPolicy, and local Athena canary transport are injected.
- The integration boundary is outside Research and Decision. It sends only canonical PortfolioSnapshot, ExecutionMandate, ExecutionResult, and snapshot JSON through a bounded local subprocess session.
- The canary projects a mandate only for BUY/ADD and validates that Athena submitted the exact decision delta or zero. It never retries UNKNOWN.
- A development-only one-shot runner requires an explicit simulation confirmation, the default-off feature flag, an account match, an allowlisted symbol, and a canonical policy file. It does not touch launchd or a plist.
- P1B artifacts remain private runtime objects pending P1C scorecard persistence.

## P1C Minimal Single Decision Scorecard

- Every completed P1B canary lineage is persisted once in the existing DSA SQLAlchemy database, keyed uniquely by `decision_id`; the stored canonical payload is immutable and content-hashed.
- The one scorecard reconstructs `ResearchBundle`, authoritative Snapshot A mirror, `RiskPolicy`, `InvestmentDecision`, `DecisionSignal`, optional `ExecutionMandate`, `ExecutionResult`, and authoritative Snapshot B mirror.
- Immediate diagnostics record requested, submitted, filled, and remaining quantity; average fill; fees; slippage; execution state; and reconciliation state without introducing performance judgment.
- An additive GET-only endpoint, `/api/v1/decision-scorecards/{decision_id}`, exposes the lineage through existing DSA API conventions. There is no scorecard mutation endpoint.
- Scorecard persistence occurs only after P1B returns observed artifacts. A storage failure is reported without changing the decision, retrying execution, or mutating portfolio truth.
- The scorecard package imports neither the Brain engine nor the mandate projector and exposes no decide, submit, retry, reconcile, or portfolio-mutation operation.

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
| P1A pure analysis-completion shadow wiring | `src/investment/shadow_wiring.py` |
| Real analysis completion integration hook | `src/core/pipeline.py` |
| P1 deterministic risk-budget target sizing | `src/investment/decision/sizing.py` |
| P1B canary orchestration and invariant checks | `src/investment/canary.py` |
| Narrow canonical local Athena transport | `src/investment/integration/canary_transport.py` |
| Explicit development one-shot runner | `scripts/run_p1_simulation_canary.py` |
| Immutable Single Decision Scorecard model | `src/investment/scorecard.py` |
| Write-once scorecard persistence | `src/repositories/decision_scorecard_repo.py` |
| Read-only scorecard service and API | `src/services/decision_scorecard_service.py`, `api/v1/endpoints/decision_scorecards.py` |

## Authority proof

- Final quantity is computed only by `InvestmentDecisionEngine` and stored in `InvestmentDecision`.
- `ExecutionMandateProjector.project()` receives no quantity argument; it binds the mandate quantity to `decision.delta_quantity`.
- The decision binds the exact research IDs, portfolio snapshot ID/hash, policy ID/version, cycle ID, and model provenance.
- Athena `PortfolioSnapshot` is consumed as immutable, authoritative, read-only account truth.

## Verification evidence

P1A validation completed on the stacked branch:

- Required DSA backend gate: `PATH=/private/tmp/dsa-athena-p0-ci/bin:$PATH ./scripts/ci_gate.sh` — syntax and critical flake8 checks passed; deterministic code/YFinance checks passed; offline suite **5782 passed, 4 deselected, 501 subtests passed**.
- P1A, config-registry, P0 contract/architecture/cross-repository, and pipeline-context focused suite — **120 passed**.
- The P1A tests drive the existing `StockAnalysisPipeline.analyze_stock()` completion path through history persistence, then verify that the resulting real `AnalysisResult` fields form the `ResearchBundle` and preserve complete decision lineage.
- Static dependency and call-surface assertions prove the shadow service has no HTTP, queue, broker, mandate, execution, dispatch, submit, persistence, mutation, or retry path.
- P1B focused DSA/P0/config/cross-repository suite — **107 passed**.
- The P1B integration test drives a real saved DSA `AnalysisResult`, produces risk-derived ADD 200, transports the canonical mandate to the sibling Athena worker, observes exact submit 200, and validates authoritative Snapshot B quantity 500.
- Cross-repository invariant: `decision.delta_quantity == mandate.quantity == execution.requested_quantity == execution.submitted_quantity == 200`; reconciled position equals Snapshot A quantity plus observed fill.
- Critical lint and diff checks passed.
- P1C scorecard/canary/P1A/architecture/storage/config focused suite — **108 passed**.
- The P1C integration test starts from an actual sibling Athena canary result, persists the complete canonical lineage in DSA SQLite, and reads it back by `decision_id` with exact execution diagnostics.
- Write-once conflict, GET-only route, not-found handling, and no-decision/no-execution architecture assertions pass.

## Compatibility

- No existing public API was removed or changed.
- Existing `DecisionSignal` remains available as a projection.
- Existing DSA research/risk/orchestration flows remain available and are not silently routed into execution.
- No live-trading path or broker SDK dependency was added to DSA.
- P1A adds no persistence, dispatch, retry, order submission, portfolio mutation, API, or UI path.
- P1B is opt-in, local, simulation-only, allowlisted, and adds no deployed runtime or public API/UI behavior.
- P1C adds one read-only API and one additive table; it does not change existing routes, portfolio authority, execution behavior, or UI behavior.

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
- Any live, Windows-worker, launchd, or deployed-runtime canary.
- Long-term 1/5/20-day outcome evaluation, broad Scorecard UI, and mutable scorecard revisions.

## Canonical next-phase handoff

Future DSA phases must update this file in the implementation PR. Any cross-repository contract or authority change requires a coordinated Athena PR, cross-links between the two PRs, explicit wire-compatibility evidence, and matching constitutional amendments when the authority boundary changes.
