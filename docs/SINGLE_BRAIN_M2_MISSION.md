# Single Brain M2 Mission — Authoritative Daily Research Loop

**Version:** 1.0

**Approved:** 2026-08-08

**Mission status:** APPROVED — NOT STARTED

**Normative parents:**

- [Single Brain Architecture Constitution](SINGLE_BRAIN_CONSTITUTION.md)
- [Single Brain P1 Mission](SINGLE_BRAIN_P1_MISSION.md)

This document is the canonical cross-repository implementation authority for M2.
The same normative content must exist in the DSA `athena-integration` branch and
the Athena `integration` branch before implementation begins.

## 1. Mission purpose

P1 proved a development-only one-shot path from a real DSA analysis result to a
separately spawned Athena Decimal simulation runtime. M2 must connect the Single
Brain architecture to the **actual authoritative Athena simulation runtime state**
and establish a recurring, default-off DSA research/decision shadow loop.

M2 is deliberately a **shadow mission**. It improves runtime truth, recurrence,
lineage, and observability without enabling new order execution.

Target lifecycle:

    actual Athena simulation runtime
      -> authoritative PortfolioSnapshot
      -> DSA scheduled analysis completion
      -> ResearchBundle
      -> explicit RiskPolicy
      -> DSA InvestmentDecision
      -> DecisionSignal
      -> persistent shadow decision record / scorecard lineage
      -> later observed Athena PortfolioSnapshot refresh

No M2 path may submit, dispatch, retry, cancel, replace, or reconcile an order.

## 2. Canonical starting baselines

Implementation must start from:

- DSA: `athena-integration`.
- Athena: `integration`.

P1 code-tree promotion was audited before governance-only closeout:

- DSA tested head `03f4cbf989535d65797f0ef56ca1066d4f2f0b75` and P1 merge baseline `fa67418179f014d94832efaba883b6fa1a78938c` shared tree `b860792d7a8a7dac5d2d190af5da75af0e96a5c2`.
- Athena tested head `974797fdbd92835a340d3324c6294be1c117f0d2` and P1 merge baseline `915441905978a2de67786209523cf934288acac5` shared tree `2ca7a11c5379dbb94acfd0301663c2a765d41dc3`.

The later baseline-promotion commits are governance-only documentation changes.

## 3. M2A — Real Athena Runtime Snapshot Ingress

### Goal

Expose the actual Athena simulation runtime as the authoritative source of
`PortfolioSnapshot` facts consumed by DSA.

### Requirements

- Reuse the existing Athena runtime/reconciliation path where possible.
- The source must be the actual running simulation account/runtime, not a newly
  spawned Decimal broker initialized from CLI cash/position arguments.
- Athena remains the sole producer of authoritative account truth.
- DSA receives immutable canonical `PortfolioSnapshot` data only.
- DSA must not maintain or mutate an authoritative portfolio ledger.
- Snapshot identity, revision, `as_of`, reconciliation status, account mode,
  data quality, positions, active orders, cash, reserved cash, and provenance
  must reflect observed Athena state.
- Snapshot freshness must be provable. Missing or stale observation fails closed.
- The ingress boundary may be a small local/read-only interface or transport;
  it must not expose order submission methods to the M2 orchestration path.
- No broker SDK may be imported into DSA Research or Decision.
- No live account is permitted. M2 remains simulation only.

### Acceptance proof

Tests must prove that changing the Athena simulation runtime changes the next
captured `PortfolioSnapshot` through observation/reconciliation rather than DSA
inference or local mutation.

## 4. M2B — Recurring DSA Research and Decision Shadow Loop

### Goal

Use existing DSA scheduling/orchestration to run recurring investment research
and Brain decisions against real authoritative Athena runtime snapshots.

### Requirements

- Add a separate explicit M2 feature/config switch, OFF by default.
- Reuse existing DSA scheduler/orchestration conventions rather than creating a
  second scheduler framework.
- Do not modify launchd/plist or silently enable any deployed service.
- Every run creates a stable `decision_cycle_id` and deterministic per-symbol
  lineage identifiers suitable for restart/deduplication.
- The loop may analyze an explicit bounded allowlist and/or current Athena
  holdings, but must remain simulation-only and read-only with respect to
  execution.
- Every decision consumes a fresh authoritative `PortfolioSnapshot` and explicit
  `RiskPolicy`.
- Research remains facts/evidence only; target sizing and final quantity remain
  DSA Brain responsibilities.
- Existing P1 risk-budget sizing remains the BUY/ADD sizing rule for M2.
- M2 does not add SELL/REDUCE execution or conditional order execution.
- If a holding appears invalidated or unattractive but the current Brain contract
  cannot express a non-executing reduction recommendation without expanding the
  action contract, record the research/invalidation evidence and HOLD. Do not
  invent an execution-capable SELL path inside M2.
- A scheduler restart or duplicate trigger must not create duplicate persisted
  decisions for the same defined cycle/symbol/input identity.

### No execution rule

M2 orchestration must have no reachable call path to:

- `ExecutionMandate` dispatch;
- Athena execution service;
- broker submission;
- order retry;
- cancel/replace;
- portfolio mutation.

Generating an `ExecutionMandate` is unnecessary in M2 and should be avoided. If
an internal projection is retained for compatibility tests, it must be explicitly
non-dispatchable and absent from runtime transport.

## 5. M2C — Shadow Decision Persistence and Review

### Goal

Make recurring shadow decisions auditable without creating a second scorecard or
second decision authority.

### Requirements

- Reuse the Single Decision Scorecard lineage model and existing DSA persistence
  conventions where practical.
- Extend persistence only as needed to represent a **shadow decision with no
  execution artifacts**.
- A shadow record must preserve at least:
  - `research_id` / ResearchBundle;
  - authoritative Snapshot ID/hash;
  - RiskPolicy ID/version;
  - `decision_cycle_id`;
  - `decision_id`;
  - InvestmentDecision;
  - DecisionSignal;
  - mode/status showing that execution was not authorized;
  - creation time and input freshness evidence.
- Do not create a parallel "shadow score" system. This remains the same Single
  Decision lineage.
- Read-only API retrieval may be extended using existing authenticated admin API
  conventions.
- No broad UI redesign is required in M2.
- No 1/5/20-day outcome scoring is required in M2.

## 6. Operational safety and authority invariants

The following remain non-negotiable:

1. Research has no capital-allocation authority.
2. DSA Brain is the only investment decision authority.
3. Athena is the only authoritative portfolio-truth producer.
4. Athena execution remains outside M2.
5. No component may reinterpret a DSA decision into another quantity.
6. Missing/stale/unreconciled runtime truth fails closed.
7. `LIVE_TRADING` must remain exactly false for every M2 integration test/path.
8. No deployed runtime configuration is silently changed.
9. No public audit repository receives private runtime data or implementation
   commits automatically.
10. `decision_id` and `decision_cycle_id` must remain traceable through all M2
    persistence and API surfaces.

## 7. Required tests

At minimum prove:

- actual Athena simulation runtime -> authoritative canonical Snapshot;
- runtime position/cash change -> next observed Snapshot change;
- default M2 feature flag OFF -> zero recurring investment side effects;
- missing/stale/unreconciled Snapshot -> no actionable shadow decision record;
- missing/invalid RiskPolicy -> fail closed;
- one real DSA analysis completion -> ResearchBundle -> InvestmentDecision ->
  persisted shadow lineage;
- scheduler duplicate/restart -> no duplicate decision for the same cycle/input;
- multiple bounded shadow symbols cannot reach execution even if action is BUY or
  ADD;
- Research/Decision dependency guards remain intact;
- DSA has no broker/execution import in the M2 Brain path;
- Athena M2 snapshot ingress has no investment decision/sizing logic;
- authenticated read-only retrieval works and unauthenticated access remains 401;
- full required DSA and Athena regression suites remain green.

## 8. Explicitly out of scope

M2 does not include:

- live trading;
- real-money accounts;
- SELL/REDUCE execution;
- automatic stop-loss or take-profit execution;
- multi-symbol portfolio capital allocation/optimization;
- distributed queues/service discovery;
- Athena `main` promotion;
- launchd/plist changes;
- scheduler replacement;
- broad UI redesign;
- legacy decision-engine retirement;
- long-term outcome/performance scoring.

## 9. Hard-stop conditions

Implementation must stop and request owner/architecture review if:

1. the Single Brain Constitution or authority boundary must change;
2. the actual Athena simulation runtime cannot expose authoritative snapshots
   without introducing a second ledger;
3. a write-capable execution interface is required merely to read runtime truth;
4. live trading or a live broker must be enabled;
5. deployed launchd/plist/runtime configuration must be changed to implement the
   code path rather than merely to enable it later;
6. a destructive migration/deletion is required;
7. existing scorecard semantics cannot represent shadow decisions without a
   materially different product/architecture choice;
8. scheduler deduplication requires distributed coordination or a new database
   platform;
9. Athena mainline promotion becomes necessary;
10. sensitive credentials/private runtime data risk exposure to a public repo;
11. full regression cannot be restored without unrelated behavior changes;
12. two materially different product/architecture choices require owner
    preference.

Routine implementation choices are not hard stops.

## 10. Mission execution protocol

Once implementation is explicitly started, Codex should execute M2A -> M2B ->
M2C -> closeout autonomously in one Mission turn when practical.

After each phase it should:

- run focused tests;
- fix in-scope failures;
- commit the phase cleanly;
- update implementation-status documentation;
- continue automatically unless a hard stop is hit.

Final closeout must:

- run full required DSA regression;
- run full required Athena regression;
- run focused cross-repository M2 tests;
- verify contract wire compatibility and authority dependency guards;
- prove default configuration performs no M2 execution;
- update this document to `MISSION COMPLETE — READY FOR ARCHITECTURE REVIEW`;
- open cross-linked Draft PRs from new M2 branches based on the canonical
  integration branches;
- leave all PRs unmerged.

Do not begin implementation merely because this document exists. Implementation
starts only when the owner explicitly instructs Codex to execute the approved
M2 Mission.
