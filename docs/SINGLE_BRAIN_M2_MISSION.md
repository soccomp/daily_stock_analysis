# Single Brain M2 Mission — Shadow Operations Readiness

**Version:** 1.1

**Approved:** 2026-08-08

**Mission status:** MISSION COMPLETE — READY FOR ARCHITECTURE REVIEW

**Normative parents:**

- [Single Brain Architecture Constitution](SINGLE_BRAIN_CONSTITUTION.md)
- [Single Brain P1 Mission](SINGLE_BRAIN_P1_MISSION.md)

This document is the canonical cross-repository implementation authority for M2. The same normative content must exist in the DSA `athena-integration` branch and Athena `integration` branch before implementation begins.

M2 intentionally expands the original Daily Research Loop into a complete **Shadow Operations Readiness Mission**. The additional work must be operationally useful; Codex must not add artificial delays, sleeps, busywork, or unrelated scope merely to make the task run longer.

## 1. Mission purpose

P1 proved a development-only one-shot path from a real DSA analysis result to a separately spawned Athena Decimal simulation runtime. M2 must connect the Single Brain architecture to the actual authoritative Athena simulation runtime, establish recurring DSA research/decision shadow operations, persist one auditable decision lineage, prove resilience across failure/restart conditions, continuously review current holdings, expose a minimal operator-readiness surface, and complete a repeatable multi-cycle shadow burn-in.

M2 remains a **zero-execution mission**.

Target lifecycle:

    actual Athena simulation runtime
      -> authoritative PortfolioSnapshot
      -> DSA scheduled analysis completion
      -> ResearchBundle
      -> explicit RiskPolicy
      -> DSA InvestmentDecision
      -> DecisionSignal
      -> persistent shadow decision / scorecard lineage
      -> operator read-only visibility
      -> later observed Athena PortfolioSnapshot refresh
      -> next decision cycle

No M2 runtime path may submit, dispatch, retry, cancel, replace, or reconcile an order.

## 2. Canonical starting baselines

Implementation must start from:

- DSA: `athena-integration`.
- Athena: `integration`.

P1 code-tree promotion was audited before governance-only closeout:

- DSA tested head `03f4cbf989535d65797f0ef56ca1066d4f2f0b75` and P1 merge baseline `fa67418179f014d94832efaba883b6fa1a78938c` shared tree `b860792d7a8a7dac5d2d190af5da75af0e96a5c2`.
- Athena tested head `974797fdbd92835a340d3324c6294be1c117f0d2` and P1 merge baseline `915441905978a2de67786209523cf934288acac5` shared tree `2ca7a11c5379dbb94acfd0301663c2a765d41dc3`.

Later baseline-promotion and M2-governance commits are documentation-only until implementation starts.

## 3. M2A — Authoritative Athena Runtime Snapshot Ingress

### Goal

Expose the actual long-running Athena simulation runtime as the authoritative source of `PortfolioSnapshot` facts consumed by DSA.

### Requirements

- Reuse the existing Athena runtime/reconciliation path where possible.
- The source must be the actual running simulation account/runtime, not a newly spawned Decimal broker initialized from CLI cash/position arguments.
- Athena remains the sole producer of authoritative account truth.
- DSA receives immutable canonical `PortfolioSnapshot` data only.
- DSA must not maintain or mutate an authoritative portfolio ledger.
- Snapshot identity, revision, `as_of`, reconciliation status, account mode, data quality, positions, active orders, cash, reserved cash, and provenance must reflect observed Athena state.
- Snapshot freshness must be provable. Missing or stale observation fails closed.
- The ingress boundary may be a small local/read-only interface or transport; it must not expose order submission methods to M2 orchestration.
- No broker SDK may be imported into DSA Research or Decision.
- No live account is permitted. M2 remains simulation only.

### Acceptance proof

Tests must prove that changing the Athena simulation runtime changes the next captured `PortfolioSnapshot` through observation/reconciliation rather than DSA inference or local mutation.

## 4. M2B — Recurring DSA Research and Brain Shadow Loop

### Goal

Use existing DSA scheduling/orchestration to run recurring investment research and Brain decisions against fresh authoritative Athena runtime snapshots.

### Requirements

- Add a separate explicit M2 feature/config switch, OFF by default.
- Reuse existing DSA scheduler/orchestration conventions rather than creating a second scheduler framework.
- Do not modify launchd/plist or silently enable any deployed service.
- Every run creates a stable `decision_cycle_id` and deterministic per-symbol lineage identity suitable for restart/deduplication.
- The loop may analyze an explicit bounded allowlist and current Athena holdings.
- Every decision consumes a fresh authoritative `PortfolioSnapshot` and explicit `RiskPolicy`.
- Research remains facts/evidence only; sizing and final quantity remain DSA Brain responsibilities.
- Existing P1 risk-budget sizing remains the BUY/ADD sizing rule for M2.
- M2 does not add SELL/REDUCE execution or conditional order execution.
- Scheduler restart or duplicate trigger must not create duplicate persisted decisions for the same defined cycle/symbol/input identity.

### No execution rule

M2 orchestration must have no reachable call path to `ExecutionMandate` dispatch, Athena execution service, broker submission, order retry, cancel/replace, or portfolio mutation. Generating a runtime `ExecutionMandate` is unnecessary and should be avoided. If a compatibility-only projection remains in tests, it must be non-dispatchable and absent from runtime transport.

## 5. M2C — Shadow Decision Persistence and Review

### Goal

Make recurring shadow decisions auditable without creating a second scorecard or second decision authority.

### Requirements

- Reuse the Single Decision Scorecard lineage model and existing DSA persistence conventions where practical.
- Extend persistence only as needed to represent a shadow decision with no execution artifacts.
- Preserve at least ResearchBundle/research IDs, authoritative Snapshot ID/hash, RiskPolicy ID/version, `decision_cycle_id`, `decision_id`, InvestmentDecision, DecisionSignal, explicit shadow/non-authorized execution state, creation time, and freshness evidence.
- Do not create a parallel shadow-score system.
- Read-only API retrieval may be extended using existing authenticated admin API conventions.
- No broad UI redesign or 1/5/20-day outcome scoring is required.

## 6. M2D — Runtime Resilience and Recovery

### Goal

Prove the recurring shadow system remains correct across crashes, duplicate triggers, partial lifecycle completion, stale inputs, and temporary dependency loss.

### Required scenarios

- DSA process restart before a cycle starts.
- Restart after analysis but before persistence.
- Restart after persistence but before cycle closeout.
- Duplicate scheduler trigger for the same cycle.
- Duplicate symbol inside the same cycle input set.
- Athena snapshot ingress temporarily unavailable.
- Snapshot stale, future-dated, unreconciled, or account-mismatched.
- RiskPolicy missing, invalid, expired, or version-conflicted.
- Persistence transient failure.
- Read-only API failure must not alter decision state.
- Existing scorecard/lineage record encountered again after restart.

### Recovery rules

- Recovery may re-read facts and deterministically recompute Research/Decision when required, but must not create duplicate persisted decisions for the same canonical cycle/input identity.
- Failure must be explicit and observable; never fabricate a fresh snapshot or silently fall back to DSA-local portfolio truth.
- No recovery path may gain execution capability.
- No blind retry loop may create unbounded repeated analysis/persistence work.

## 7. M2E — Holdings Review Loop

### Goal

Ensure the Brain repeatedly reviews what the account already owns, not merely a watchlist of potential buys.

### Requirements

- Current Athena holdings must be eligible for scheduled research even when absent from the ordinary watchlist, subject to an explicit bounded policy.
- Research must preserve thesis status, catalysts, invalidation evidence, risk changes, data quality, and confidence.
- If evidence suggests thesis weakening, invalidation, or elevated risk, record that evidence clearly in the ResearchBundle and decision rationale.
- M2 must not introduce execution-capable SELL/REDUCE.
- If the current contract cannot express a non-executing reduction recommendation without expanding the action contract, remain HOLD for capital action while persisting the invalidation/risk evidence for later review.
- Do not smuggle reduction sizing into Research, DecisionSignal metadata, scorecard diagnostics, or operator UI.

### Acceptance proof

Tests must show at least one existing holding is re-researched across later cycles and that changed research evidence changes the next Brain lineage while producing zero execution side effects.

## 8. M2F — Operator Readiness Surface

### Goal

Provide a small, read-only way for an operator to answer whether the autonomous shadow system is healthy and what the Brain most recently thought.

### Minimum surface

Using existing DSA API/service/UI conventions where possible, expose read-only information for:

- latest authoritative Athena Snapshot identity/time/reconciliation state;
- latest completed `decision_cycle_id`;
- symbols analyzed in that cycle;
- latest decision/action and rationale summary per symbol;
- whether the symbol came from allowlist, holdings review, or both;
- why a cycle/symbol was skipped, blocked, stale, or failed closed;
- confirmation that execution authorization is OFF;
- last successful shadow persistence timestamp;
- duplicate/restart recovery diagnostics where relevant.

### Constraints

- No broad UI redesign.
- No mutation endpoint.
- No retry/submit/reconcile control.
- Existing global admin-session authentication must protect any new API route.
- Operator display is observational only and cannot become a second decision or execution authority.

## 9. M2G — Multi-Cycle Shadow Burn-in and Mission Closeout

### Goal

Exercise the completed M2 system repeatedly across meaningful state changes and failures before declaring it operationally ready for a future execution-capable mission.

### Burn-in harness

Build a deterministic, repeatable development/test harness that can drive many shadow cycles without real-time sleeping. It must exercise a bounded matrix including:

- multiple sequential decision cycles;
- multiple bounded symbols;
- at least one current holding;
- cash/position changes observed from Athena runtime between cycles;
- snapshot revision changes;
- research evidence changes;
- BUY/ADD/HOLD outcomes;
- stale/unavailable snapshot cases;
- duplicate scheduler triggers;
- DSA restart/recovery;
- persistence idempotency/conflict cases;
- authenticated operator-readiness retrieval.

The harness should execute enough deterministic cycles to expose lineage and dedupe defects; a practical minimum is 20 logical cycles across at least 3 symbols unless repository constraints justify a stronger equivalent matrix. Do not use wall-clock sleeps or artificial token-consuming work to prolong execution.

### Burn-in invariants

Across the whole run prove:

- every persisted decision has one canonical `decision_id` and `decision_cycle_id` lineage;
- no duplicate canonical decision records for the same cycle/input identity;
- every consumed Snapshot is Athena-produced and freshness-valid;
- DSA never becomes authoritative account truth;
- M2 generates zero broker submissions and zero reachable execution side effects;
- feature flag OFF yields zero recurring investment work;
- all failure states are explicit and recoverable or safely fail closed.

## 10. Operational safety and authority invariants

The following remain non-negotiable:

1. Research has no capital-allocation authority.
2. DSA Brain is the only investment decision authority.
3. Athena is the only authoritative portfolio-truth producer.
4. Athena execution remains outside M2.
5. No component may reinterpret a DSA decision into another quantity.
6. Missing/stale/unreconciled runtime truth fails closed.
7. `LIVE_TRADING` must remain exactly false for every M2 integration test/path.
8. No deployed runtime configuration is silently changed.
9. No public audit repository receives private runtime data or implementation commits automatically.
10. `decision_id` and `decision_cycle_id` remain traceable through all M2 persistence/API surfaces.
11. Resilience logic may recover observation/decision work but never authorize execution.
12. Operator surfaces are observational only.

## 11. Required regression and architecture tests

At minimum prove:

- actual Athena simulation runtime -> authoritative canonical Snapshot;
- runtime position/cash change -> next observed Snapshot change;
- default M2 feature flag OFF -> zero recurring investment side effects;
- missing/stale/unreconciled Snapshot -> no actionable shadow decision record;
- missing/invalid RiskPolicy -> fail closed;
- one real DSA analysis completion -> ResearchBundle -> InvestmentDecision -> persisted shadow lineage;
- scheduler duplicate/restart -> no duplicate canonical decision;
- bounded multiple symbols cannot reach execution even for BUY/ADD;
- holdings review re-analyzes existing positions;
- failure/recovery matrix from M2D passes;
- operator-readiness API remains authenticated read-only; missing/forged session -> 401;
- Research/Decision dependency guards remain intact;
- DSA has no broker/execution import in the M2 Brain path;
- Athena snapshot ingress has no investment decision/sizing logic;
- P1 exact-quantity/UNKNOWN/idempotency invariants remain unbroken even though M2 does not execute;
- full required DSA and Athena regression suites remain green.

## 12. Explicitly out of scope

M2 does not include live trading, real-money accounts, SELL/REDUCE execution, automatic stop-loss/take-profit execution, multi-symbol portfolio optimization, distributed queues/service discovery, Athena `main` promotion, launchd/plist changes, scheduler replacement, broad UI redesign, legacy decision-engine retirement, or long-term outcome/performance scoring.

## 13. Hard-stop conditions

Implementation must stop and request owner/architecture review if:

1. the Single Brain Constitution or authority boundary must change;
2. actual Athena simulation runtime cannot expose authoritative snapshots without introducing a second ledger;
3. a write-capable execution interface is required merely to read runtime truth;
4. live trading or live broker must be enabled;
5. deployed launchd/plist/runtime configuration must change to implement the code path rather than merely to enable it later;
6. destructive migration/deletion is required;
7. existing scorecard semantics cannot represent shadow decisions without a materially different product/architecture choice;
8. scheduler deduplication requires distributed coordination or a new database platform;
9. Athena mainline promotion becomes necessary;
10. sensitive credentials/private runtime data risk exposure to a public repo;
11. full regression cannot be restored without unrelated behavior changes;
12. two materially different product/architecture choices require owner preference;
13. zero-execution isolation cannot be proven;
14. holdings review would require adding executable SELL/REDUCE authority.

Routine implementation choices are not hard stops.

## 14. Mission execution protocol

Once implementation is explicitly started, Codex should execute **M2A -> M2B -> M2C -> M2D -> M2E -> M2F -> M2G -> closeout autonomously in one Mission turn when practical**.

After each phase Codex must run focused tests, fix in-scope failures, commit the phase cleanly, update implementation-status documentation, and continue automatically unless a hard stop is hit. Routine clarification, naming, file placement, test organization, and in-scope refactoring are not reasons to pause.

Final closeout must:

- run full required DSA regression;
- run full required Athena regression;
- run focused cross-repository M2 suites including resilience and multi-cycle burn-in;
- verify contract wire compatibility and authority dependency guards;
- prove default configuration performs no M2 work and enabled M2 performs no execution;
- update this document to `MISSION COMPLETE — READY FOR ARCHITECTURE REVIEW` with exact evidence and known gaps;
- update both implementation-status documents;
- open cross-linked Draft PRs from new M2 branches based on the canonical integration branches;
- leave all PRs unmerged.

Do not begin implementation merely because this document exists. Implementation starts only when the owner explicitly instructs Codex to execute the approved M2 Mission.

## 15. Mission closeout evidence

M2A through M2G are implemented on the canonical integration-derived branches and published for architecture review:

- DSA Draft PR: [soccomp/daily_stock_analysis#4](https://github.com/soccomp/daily_stock_analysis/pull/4), base `athena-integration`, head `codex/m2-shadow-operations`.
- Athena Draft PR: [soccomp/athena#3](https://github.com/soccomp/athena/pull/3), base `integration`, head `codex/m2-shadow-operations`.
- Both PRs are cross-linked, Draft, and unmerged.

Verification completed on 2026-08-08:

- DSA required `./scripts/ci_gate.sh`: syntax, critical flake8, deterministic code/YFinance checks, then **5,839 passed, 4 deselected, 501 subtests passed**.
- DSA M2 focused auth, architecture, resilience, holdings, cross-repository, scheduler, and burn-in suite: **52 passed**.
- Athena full regression: **916 passed**.
- Athena M2A plus Trading Spine/worker focused suite: **92 passed**.
- The deterministic burn-in completed 20 successful cycles across three symbols, persisted 60 unique BUY/ADD/HOLD shadow scorecards, exercised duplicate/restart and stale/unavailable cases, and produced no mandate, result, Snapshot B, submission, cancellation, retry, or reconciliation side effect.
- Cross-repository wire proof observed changing Athena runtime projections, preserved canonical IDs, Decimal strings, timezone-aware timestamps and content hashes in DSA, and recorded zero submissions/cancellations.
- Default configuration registers no M2 work. Enabled M2 remains `execution_authorization=OFF`; `LIVE_TRADING` remains exactly false in the Athena boundary.

Known gaps intentionally remain outside M2:

- The feature is not enabled in any deployed DSA or Athena service; no launchd/plist/runtime configuration was changed.
- Weakening holdings remain HOLD with explicit risk/invalidation evidence because SELL/REDUCE authority and execution are outside M2.
- Recovery/idempotency uses the existing single-database SQLite deployment model; distributed workers, queues, and cross-host coordination remain out of scope.
- Operator visibility is the authenticated read-only API; no broad UI was added.
- Athena `main` promotion and synchronization to the sanitized public `soccomp/audit-athena` snapshot remain separate governance decisions.
- Any future execution-capable phase requires a new explicit mission and architecture acceptance; M2 itself grants no execution authority.
