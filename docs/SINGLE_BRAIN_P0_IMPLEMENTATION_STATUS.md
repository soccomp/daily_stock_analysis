# Single Brain P0/P1 Implementation Status — DSA

**Status date:** 2026-08-08

**Repository role:** Research and sole Investment Decision Brain

**Lifecycle state:** M2 IN PROGRESS — M2D COMPLETE

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

The existing DSA agent, screening, portfolio, API, and Web flows remain in place. This is an additive P0/P1 path; DSA's existing local portfolio service is not used as authoritative truth for an Athena-integrated account.

## M2B Recurring Brain Shadow Loop

- `DSA_SINGLE_BRAIN_M2_ENABLED=false` is a separate default-off switch. Disabled mode registers no M2 scheduler task and performs no Athena observation, research, decision, or persistence work.
- The existing API/Web/Desktop runtime scheduler and CLI schedule mode both register the same bounded M2 background task and share the existing global analysis lock. No second scheduler, launchd/plist edit, or deployed enablement was introduced.
- DSA reads only canonical `PortfolioSnapshot` JSON from Athena's exact loopback `GET /v1/simulation/portfolio-snapshot` route. The client rejects alternate paths, credentials, queries, redirects before follow-up contact, oversized payloads, and invalid hashes/contracts; it imports no Athena or broker implementation.
- Every logical time slot has a deterministic `decision_cycle_id`; each bounded CN symbol has a deterministic analysis query and decision identity. Current Athena holdings are deduplicated with the explicit allowlist under a configurable cap.
- An additive SQLite operational checkpoint uses unique cycle/symbol keys and stores only immutable Snapshot A and RiskPolicy mirrors plus scheduler recovery facts. It is not an account ledger or parallel scorecard. Duplicate/restart work reuses the exact bound inputs, while conflicting Snapshot, policy hash, policy content, or symbol scope fails closed.
- The real DSA `StockAnalysisPipeline` remains the analysis producer. M2 disables all pre-existing P1 investment runtime hooks during that analysis, reconstructs the persisted completion deterministically, revalidates authority/freshness after analysis, and then invokes only the DSA Brain shadow service. Runtime mandate creation and all execution transport are absent.
- Focused M2B ingress/scheduler/analysis/dedupe tests: **32 passed** at the phase checkpoint.

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

## M2C Shadow Decision Persistence

- M2 reuses the existing `SingleDecisionScorecard` model, write-once repository, `decision_id` key, and authenticated read surface. No parallel shadow score or second decision authority was introduced.
- `SingleDecisionScorecard.from_shadow()` records ResearchBundle, exact authoritative Snapshot A mirror/hash, RiskPolicy/version/hash, `decision_cycle_id`, InvestmentDecision, DecisionSignal, creation time, and freshness provenance with explicit `mode=M2_SHADOW`, `execution_authorization=OFF`, and `execution_state=NOT_AUTHORIZED` diagnostics.
- BUY, ADD, and HOLD shadow decisions all require zero `ExecutionMandate`, zero `ExecutionResult`, and no Snapshot B. Any attempt to attach execution artifacts to an M2 shadow scorecard fails validation.
- `DecisionScorecardService.persist_shadow()` keeps the existing immutable create-if-absent semantics. Restart or duplicate persistence with identical content returns the same record; conflicting content under one `decision_id` is rejected.
- M2C plus P1 scorecard/shadow/canary focused regression: **22 passed** at the phase checkpoint.

## M2D Runtime Resilience and Recovery

- Cycle and symbol claims are durable and unique. A duplicate scheduler trigger, duplicate symbol, or process restart reuses the same deterministic analysis query, `decision_cycle_id`, and `decision_id` rather than creating a second scorecard.
- Recovery after real analysis persistence reconstructs the saved DSA result; recovery after scorecard persistence skips both analysis and scorecard rewriting, then closes the existing cycle checkpoint.
- The exact immutable Snapshot A, symbol scope, and RiskPolicy are rebound on recovery. A missing, changed, expired, or conflicting policy and unavailable, stale, future, unreconciled, or account-mismatched Athena snapshot fail closed with no actionable lineage.
- Storage failures are bounded to one scheduler attempt. Analysis, scorecard persistence, and cycle closeout failure injection remains recoverable without retry loops or any execution path.
- M2D resilience plus shadow/scorecard focused regression: **23 passed** at the phase checkpoint.

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

- P1A required DSA backend gate completed with syntax, critical flake8, deterministic checks, and offline suite **5782 passed, 4 deselected, 501 subtests passed**.
- P1A/config/P0 architecture/cross-repository/pipeline focused suite — **120 passed**.
- P1B focused DSA/P0/config/cross-repository suite — **107 passed**.
- The P1B integration test drives a real saved DSA `AnalysisResult`, produces risk-derived ADD 200, transports the canonical mandate to the sibling Athena worker, observes exact submit 200, and validates authoritative Snapshot B quantity 500.
- Cross-repository invariant: `decision.delta_quantity == mandate.quantity == execution.requested_quantity == execution.submitted_quantity == 200`; reconciled position equals Snapshot A quantity plus observed fill.
- P1C scorecard/canary/P1A/architecture/storage/config focused suite — **108 passed**.
- The P1C integration test starts from an actual sibling Athena canary result, persists the complete canonical lineage in DSA SQLite, and reads it back by `decision_id` with exact execution diagnostics.
- Write-once conflict, GET-only route, not-found handling, and no-decision/no-execution architecture assertions pass.
- Post-architecture-review auth regression — **113 passed** for the relevant P1/auth suite. The real `create_app` + global `AuthMiddleware` path returns 401 for a missing or forged `dsa_session`; a real `/api/v1/auth/login` signed admin session reaches the Scorecard GET endpoint and returns 200.
- Final P1 DSA required backend gate — **5793 passed, 4 deselected, 501 subtests passed**.
- Paired Athena full/focused regressions — **883 / 45 passed**.

## Compatibility

- No existing public API was removed or changed.
- Existing `DecisionSignal` remains available as a projection.
- Existing DSA research/risk/orchestration flows remain available and are not silently routed into execution.
- No live-trading path or broker SDK dependency was added to DSA.
- P1A adds no persistence, dispatch, retry, order submission, portfolio mutation, API, or UI path.
- P1B is opt-in, local, simulation-only, allowlisted, and adds no deployed runtime or public API/UI behavior.
- P1C adds one read-only API and one additive table; it does not change existing routes, portfolio authority, execution behavior, or UI behavior.

## Publication and upstream policy

- The canonical Athena-specific DSA development branch is `athena-integration` in `soccomp/daily_stock_analysis`.
- DSA `main` remains upstream-oriented and is intentionally not the canonical branch for Athena-specific integration work.
- No P0/P1 PR is opened automatically against `ZhuLinsen/daily_stock_analysis`.
- The current Single Brain implementation is not demonstrably generic as-is: its canonical contracts, authoritative snapshot rules, execution mandate lineage, simulation-only restrictions, and cross-repository tests intentionally encode the DSA/Athena boundary.
- Governance is system-specific and must not be upstreamed independently without upstream agreement on the Single Brain constitution.
- A future upstream proposal should be a separately authored extraction rather than a direct merge of the Athena-integration history.

## Intentionally out of P1

- Multiple simultaneous symbols or decision-cycle portfolio allocation.
- SELL/REDUCE execution, complex conditional stops, and take-profit automation.
- Live trading, message queues, service decomposition, or repository merger.
- Full Decision Scorecard UI and broad DSA Web UI integration.
- Retirement of legacy DSA or Athena investment paths.
- Any live, Windows-worker, launchd, or deployed-runtime canary.
- Long-term 1/5/20-day outcome evaluation, broad Scorecard UI, and mutable scorecard revisions.

## P1 Baseline Promotion

Architecture acceptance and auth closeout completed before promotion. The stacked DSA PRs were merged in dependency order into `athena-integration`:

- PR #1 P0 merge commit: `fe488d3ff9c8ebe343fd4b6c188ae7aa6d88aa08`.
- PR #2 P1A merge commit: `02daef3a85b24ca71fc49e1b009f854792231e8d`.
- PR #3 P1 merge baseline: `fa67418179f014d94832efaba883b6fa1a78938c`.

The accepted/tested DSA P1 head `03f4cbf989535d65797f0ef56ca1066d4f2f0b75` and merge baseline `fa67418179f014d94832efaba883b6fa1a78938c` both point to tree `b860792d7a8a7dac5d2d190af5da75af0e96a5c2`. The merge therefore introduced no code-tree drift.

The canonical paired Athena baseline is `integration`, whose accepted P1 merge baseline is `915441905978a2de67786209523cf934288acac5`. Its tree matches the tested Athena P1 head exactly, as recorded in [P1 Mission](SINGLE_BRAIN_P1_MISSION.md).

## Canonical next-phase handoff

Future DSA missions must branch from **`athena-integration`** and read [P1 Mission](SINGLE_BRAIN_P1_MISSION.md) plus the Constitution before implementation. The paired Athena branch is **`integration`**.

Any cross-repository contract or authority change requires coordinated DSA and Athena changes, explicit wire-compatibility evidence, and matching constitutional amendments when the authority boundary changes. Athena mainline promotion remains a separate governance decision and must not be folded into an unrelated mission.
