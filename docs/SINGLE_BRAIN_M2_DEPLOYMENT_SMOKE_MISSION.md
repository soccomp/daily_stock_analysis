# Single Brain M2 Deployment Smoke Mission

**Version:** 1.1

**Approved:** 2026-08-09

**Mission status:** APPROVED — RESTART FROM S0

**Normative parents:**

- `docs/SINGLE_BRAIN_CONSTITUTION.md`
- `docs/SINGLE_BRAIN_M2_MISSION.md`
- `docs/SINGLE_BRAIN_M2_BASELINE_STATUS.md`

This mission is the first controlled proof of the accepted M2 code against the actually running simulation deployment. It is not an execution-capable trading mission.

## 1. Objective

Prove one real deployed zero-execution path:

    actually running Athena simulation runtime
      -> authoritative canonical PortfolioSnapshot
      -> actually running/controlled DSA analysis path
      -> ResearchBundle
      -> explicit RiskPolicy
      -> DSA InvestmentDecision
      -> DecisionSignal
      -> M2 shadow scorecard
      -> local read-only operator-readiness readback

The proof must use observed account facts from the real long-running Athena simulation environment, not fixture state and not a newly seeded Decimal broker.

The Owner's current deployment policy intentionally keeps DSA passwordless with
`ADMIN_AUTH_ENABLED=false`. This is the accepted and expected state for this
smoke. The readiness surface must remain loopback/local-only and observational;
this mission must not enable authentication, add a password, or introduce a new
authentication mechanism.

## 2. Canonical code baselines

Start only from the accepted M2 integration branches:

- DSA: `athena-integration`, accepted M2 merge baseline `38a20aaf8fe9d27873c2acb1f0152728734fe8be` plus later governance-only commits.
- Athena: `integration`, accepted M2 merge baseline `3840bf8bc9c381c1129f7114486b0a6f40e56ffb` plus later governance-only commits.

Do not implement new investment logic in this mission.

## 3. Phase S0 — Read-only deployment preflight

Before changing any running process or configuration, inspect and record:

- which Athena simulation process is actually running;
- which repository/worktree/commit that process uses;
- which DSA process/service is actually running;
- which repository/worktree/commit that process uses;
- simulation account identity and account mode;
- `LIVE_TRADING` state;
- current loopback/runtime endpoints and ports;
- whether the accepted canonical snapshot endpoint is already present;
- whether M2 feature flags are currently disabled;
- whether DSA remains bound to loopback/local-only access;
- whether `ADMIN_AUTH_ENABLED=false` remains effective;
- current relevant process health and last observed account timestamp.

S0 is read-only. Do not restart, stop, edit plist/service files, change credentials, change account configuration, or enable M2 during preflight.

If the real deployment cannot be identified unambiguously, stop with `HARD STOP: DEPLOYMENT_IDENTITY_UNCLEAR`.

## 4. Phase S1 — Authoritative runtime snapshot smoke

If the accepted M2 code is already available in the running Athena simulation deployment without a service/config mutation, capture at least two canonical PortfolioSnapshots from the real runtime and prove:

- `source=ATHENA_RUNTIME`;
- `authoritative=true`;
- `read_only=true`;
- `simulation_only=true`;
- reconciled state;
- timezone-aware fresh `as_of`;
- stable account identity;
- observed cash, positions, active orders, revision, provenance, and hashes;
- the second observation is a new observation/revision according to the canonical adapter semantics;
- zero order submission/cancellation/retry/reconciliation side effects are introduced by the smoke path.

If exposing the accepted endpoint requires changing a running service, deployment file, launchd/plist, Windows service/task, credential flow, network policy, or restarting a production-like simulation process, do not perform that mutation under this mission automatically. Stop with `HARD STOP: DEPLOYMENT_CHANGE_REQUIRED` and provide the smallest reversible change plan.

## 5. Phase S2 — One controlled DSA shadow cycle

Proceed only if S1 passes and the DSA process can consume the real canonical snapshot without deployment mutation beyond already-approved runtime configuration.

Requirements:

- M2 execution authorization remains OFF.
- Use one explicitly allowlisted CN symbol, preferably one current simulated holding when available.
- Use one explicit canonical RiskPolicy.
- Run exactly one controlled M2 shadow decision cycle.
- Produce one real persisted DSA analysis completion, ResearchBundle, InvestmentDecision, DecisionSignal, and shadow scorecard lineage.
- No ExecutionMandate, ExecutionResult, Snapshot B, broker submission, cancellation, retry, reconcile, or portfolio mutation.
- Capture the resulting `decision_cycle_id` and `decision_id`.
- Re-trigger the same defined cycle once only to prove deduplication without duplicate scorecard persistence.

Do not leave recurring scheduling enabled after the smoke. If a temporary in-process/config toggle is used under an already-running non-deployed test process, restore it to OFF before closeout.

## 6. Phase S3 — Local read-only operator-readiness proof

Under the Owner-approved passwordless deployment policy:

- `ADMIN_AUTH_ENABLED=false` is expected;
- DSA remains bound to loopback/local-only access;
- local `GET /api/v1/single-brain/m2/readiness` returns 200;
- readiness identifies the smoke cycle/symbol/decision and explicitly reports execution authorization OFF;
- the readiness surface is observational and read-only only;
- no POST, PUT, PATCH, DELETE, retry, submit, reconcile, portfolio mutation, or execution-control endpoint is available through the M2 readiness path;
- `DSA_SINGLE_BRAIN_M2_ENABLED=false` before and after the controlled smoke;
- Athena remains `LIVE_TRADING=false` and `simulation_only=true`.

Do not enable authentication, add a password, or introduce a new authentication
mechanism as part of this smoke.

Do not expose credentials, cookies, account secrets, or private runtime payloads in GitHub artifacts.

## 7. Evidence package

Record a sanitized smoke report containing:

- exact DSA and Athena commit SHAs used;
- process/runtime identity in non-secret form;
- snapshot IDs/hashes/timestamps and reconciliation state;
- decision cycle ID and decision ID;
- symbol scope;
- shadow action;
- proof of duplicate-cycle dedupe;
- proof execution authorization stayed OFF;
- explicit zero submission/cancel/retry evidence;
- focused smoke-test results;
- any deployment gap encountered.

Do not commit raw credentials, broker tokens, cookies, private account numbers, or unredacted sensitive runtime dumps.

## 8. Explicitly forbidden

This mission does not authorize:

- live trading or real-money accounts;
- order submission of any kind;
- SELL/REDUCE execution;
- automatic stop/take-profit execution;
- cancel/replace/retry/reconciliation commands;
- portfolio mutation;
- changing Athena investment authority;
- changing DSA/Athena Single Brain authority boundaries;
- Athena `main` promotion;
- public audit-repository synchronization;
- destructive migration;
- broad UI work;
- unrelated launchd/plist/path cleanup.

## 9. Hard stops

Stop and request owner review if:

1. `LIVE_TRADING` is not exactly false;
2. the observed account is not simulation-only;
3. deployed process identity or repository ancestry is ambiguous;
4. accepted M2 code cannot be reached without a running-service/deployment mutation;
5. a service restart or launchd/plist/Windows service/task change is required;
6. credentials/network permissions must be broadened;
7. canonical snapshot freshness/reconciliation cannot be proven;
8. zero-execution isolation cannot be proven;
9. the real runtime exposes different semantics from the accepted M2 contract;
10. the smoke would require a new investment/product choice;
11. unrelated regressions appear;
12. secret/private account data would need to be committed or published.

## 10. Completion states

The mission may close in exactly one of two states:

### SMOKE PASS

One real Athena simulation Snapshot -> one real DSA shadow cycle -> one persisted shadow scorecard -> local read-only readiness readback succeeds with zero execution side effects. Restore all temporary toggles to OFF and publish only sanitized evidence.

### HARD STOP

No unsafe workaround. Record the exact blocker and the smallest reversible owner-approved deployment action required next.

Do not merge or promote any new code automatically. If implementation code changes become necessary, open separate Draft PRs and return for architecture review.
