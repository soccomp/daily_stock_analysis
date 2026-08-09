# Single Brain M2 Deployment Smoke Mission

**Version:** 1.5

**Approved:** 2026-08-09

**Mission status:** DEPLOYMENT SMOKE PASS

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

## 11. Deployment smoke record — 2026-08-09

The Owner-approved passwordless acceptance revision was published first at DSA
commit `545e93504d0cf34508e3479ed8bcb28520314057`. The smoke then restarted from
S0 against the already aligned deployment.

### S0 — PASS

- DSA ran the accepted `athena-integration` code tree plus governance-only
  commits, bound only to `127.0.0.1:8080`, with the existing `--webui-only`
  service command.
- Athena remained the aligned simulation Worker recorded at
  `integration@19c36d328d28a024a927f612b910f85db04c22b1` and was reachable only
  through the existing loopback tunnel.
- `ADMIN_AUTH_ENABLED=false` was the expected Owner-approved state.
- `DSA_SINGLE_BRAIN_M2_ENABLED`, the P1A runtime shadow hook, and the P1B canary
  all remained OFF.
- Athena health reported `LIVE_TRADING=false`, `simulation_only=true`, and
  `READY`. Existing DSA Git/database/plist and Athena Worker rollback evidence
  remained available.

### S1 — PASS

Two real canonical observations produced revisions 8 and 9:

- Snapshot A: `snapshot:athena-sim:8:d7a56c0c7e2575fe`, hash
  `48879645558634825f938cf8f5d06b2d13bed64ee1b1efdb2c94d64ca144c312`;
- Snapshot B: `snapshot:athena-sim:9:2c422b91c993ffc6`, hash
  `74ea89dfd8d33c4a22497b0265914dac90c4bdf9be26bf74c1c36d2d7f7db25e`.

Both were fresh, reconciled, Athena-owned, authoritative, read-only,
simulation-only, hash-valid, and carried the accepted runtime provenance. The
stable account fingerprint, order evidence, and position/cash mutation facts
remained unchanged across S1. No submit, cancel, retry, reconcile, or portfolio
mutation call was made.

### S2 — HARD STOP

The one-shot process used an in-memory-only M2 enablement while the deployed
configuration remained OFF. The production `M2ShadowLoopService` recorded its
validation clock immediately before requesting the authoritative snapshot. The
Athena endpoint necessarily created the observation a few milliseconds later,
so the fresh snapshot appeared future-dated relative to that earlier clock and
the cycle failed closed with:

`authoritative PortfolioSnapshot is future-dated`

Failed cycle: `m2-cycle-75f601dbcf829fe21c384bd6b61a01734838e1c2`.

The failure occurred before analysis. Analysis-history count remained 13,
scorecard count remained zero, and no per-symbol checkpoint, ResearchBundle,
InvestmentDecision, DecisionSignal, duplicate trigger, mandate, result, or
Snapshot B was created. Readiness reported the failed-closed cycle and
`execution_authorization=OFF`.

Closeout re-confirmed one unchanged historical order and one unchanged
historical execution with the same sanitized evidence digest as S1. Recurring
M2 scheduling, P1A, and P1B remained OFF; Athena remained simulation-only with
`LIVE_TRADING=false`. No service, plist, environment, credential, password,
network permission, or runtime process was changed or restarted.

Do not rerun S2 until a separately reviewed code change corrects the caller /
observation clock ordering while preserving strict future-dated and stale
snapshot rejection.

## 12. Authoritative Snapshot clock diagnosis — 2026-08-09

Deployment Smoke remained stopped. No S2 retry or S3 work was performed.

### Timestamp ownership

| Field | Clock owner and current meaning |
| --- | --- |
| Worker request observation time | Windows Worker `datetime.now(timezone.utc)`, sampled at the start of `canonical_portfolio_observation()` before the broker cash/position/order GET sequence. |
| Underlying runtime/broker observation time | The broker APIs expose no atomic portfolio timestamp in this path. The Worker assigns its request observation time to the aggregate runtime observation and each position `price_as_of`. |
| Canonical `PortfolioSnapshot.as_of` | Athena ingress preserves the Worker `observed_at` exactly. |
| Envelope `created_at` | The current adapter sets it to that same preserved Worker observation time; it is not a separately sampled ingress/response time. |
| `revision` / `supersedes_id` | Athena ingress owns the persisted sequence. The observation timestamp participates in the fact identity, so each fresh observation creates the next immutable revision and supersedes the prior snapshot. |
| DSA validation time | The M2 loop currently samples the DSA/macOS clock before issuing the canonical HTTP GET, then compares the later Athena observation against that earlier value. |

### Real deployed observations

Five consecutive canonical observations were captured read-only:

| Revision | Snapshot ID | Supersedes | `as_of` = `created_at` = Worker/runtime observation | Hash | Reconciliation |
| --- | --- | --- | --- | --- | --- |
| 15 | `snapshot:athena-sim:15:2e42df6018b80018` | `snapshot:athena-sim:14:e8435a512bc7a982` | `2026-08-08T16:47:26.281126Z` | `086d8c879d68adbd6dd60b498d855124c41860f98274ccf925e867066b320d6c` | RECONCILED |
| 16 | `snapshot:athena-sim:16:482c5b9bf9c0a6b5` | revision 15 | `2026-08-08T16:47:26.336784Z` | `6703ab237a10b3b9e4ba080061594a3ba5a55dd01b1938f80deee24e64e4c18a` | RECONCILED |
| 17 | `snapshot:athena-sim:17:e4b57e3155f2dbca` | revision 16 | `2026-08-08T16:47:26.395155Z` | `04982ffe954627bbf13eb40385c84304c22f733994f4ba2d7de3daeafd8f3f52` | RECONCILED |
| 18 | `snapshot:athena-sim:18:8be23ed2424030bb` | revision 17 | `2026-08-08T16:47:26.446722Z` | `c6e3bebf53d018a32ca17fb0a0ae66373109dd6ee384b41d7ac36004160026c8` | RECONCILED |
| 19 | `snapshot:athena-sim:19:415f97316e4a33bc` | revision 18 | `2026-08-08T16:47:26.499015Z` | `8cd95d21a1d5d5bb8136951f7d6c53416ebd7e5f51b1b48194a8a653e08acc3a` | RECONCILED |

The exact monotonic revision and supersession chain excludes unchanged broker
observation time, ingress timestamp reuse, non-monotonic lineage, and persisted
restart-state corruption as causes. Windows timezone conversion is also
correct: the host reports `China Standard Time` / UTC+08:00 and emits aware UTC
timestamps.

Twelve independent HTTP observations showed the Worker timestamp consistently
ahead of the DSA host's post-response clock by 52.812–62.040 ms (median 59.023
ms), with 41.369–45.942 ms request round trips. Therefore two conditions combine:

1. DSA compares against a clock sampled before the remote observation exists;
2. the independent Windows wall clock is also slightly ahead of the DSA host,
   so merely moving DSA's sample after the GET still does not restore strict
   ordering.

### Decision gate

No arbitrary sleep or timestamp replacement was used. No tolerance was added
and no future/freshness validation was weakened.

A correct cross-host repair now requires a normative choice among at least:

- an explicit, bounded, evidenced cross-host clock-skew budget;
- a distinct Athena ingress/response timestamp and causal validation rule; or
- an operational clock-synchronization SLA and its fail-closed enforcement.

Those choices define how `as_of`, envelope creation time, and future-dated
authoritative observations are interpreted across hosts. Per mission authority,
that semantic decision is not made autonomously. No implementation branch or
Draft PR was created.

Safety closeout remained unchanged: `LIVE_TRADING=false`, simulation-only,
recurring M2/P1A/P1B OFF, and the one historical order/execution evidence digest
unchanged. No submit, cancel, retry, reconcile, portfolio mutation, service
restart, credential, password, plist, or environment change occurred.

## 13. Owner-approved Snapshot clock semantics and repair — 2026-08-09

The Owner resolved the Section 12 contract decision without changing the Single
Brain authority boundary:

- `PortfolioSnapshot.as_of` remains Athena's authoritative factual observation
  time and `created_at` remains the producer-side canonical object creation
  time. DSA does not rewrite either value.
- Snapshot causal ordering remains the monotonic `revision` / `supersedes_id`
  chain rather than exact cross-host wall-clock equality.
- DSA records a consumer-only UTC receipt clock only after the complete
  canonical HTTP response has been received.
- M2 authority validation has a fixed one-second cross-host infrastructure
  clock-skew budget. An `as_of` ahead of receipt by at most one second is
  accepted with freshness age zero for that calculation only; a value more than
  one second ahead still fails closed. The existing five-minute stale limit is
  unchanged.

The integration-derived DSA repair changes no canonical schema, serialization,
hash input, portfolio authority, RiskPolicy, investment sizing, scheduler
enablement, or execution path. Focused DSA P0/P1/M2, contract, architecture,
restart/deduplication, and cross-repository regression completed with **106
passed**. The full DSA backend gate completed with **5,846 passed, 4 deselected,
501 subtests passed**. Paired Athena canonical-contract, M2 runtime-snapshot,
and architecture compatibility regression completed with **46 passed**.

The repair is review-only. It has not been deployed or merged, Deployment Smoke
has not resumed, recurring M2 remains OFF, and no submit, cancel, retry,
reconcile, or portfolio mutation operation was performed.

## 14. Owner-approved cash representation-equivalence closeout rule — 2026-08-09

The prior Smoke closeout gate identified a `+0.00000000012` CNY difference in
Athena producer-observed available cash. The Owner has approved the following
strictly limited rule for the remaining zero-mutation proof.

### Canonical factual equality remains unchanged

`PortfolioSnapshot` cash fields remain Athena producer facts. Their Decimal
strings, canonical JSON, content hashes, and all Brain inputs must remain exact.
Neither DSA nor the Smoke verifier may quantize, rewrite, normalize, or re-hash
the canonical snapshot to hide a difference. Canonical factual equality still
means exact contract-field equality.

### Smoke-only zero-mutation semantic equivalence

For Deployment Smoke closeout evidence only, two observed broker monetary values
originating from binary64 fields may be treated as representation-equivalent
when all of the following are proved:

- the difference is explicitly attributed to `NUMERIC_REPRESENTATION_JITTER`;
- the values compare equal at the CNY currency quantum of `0.01`;
- position quantity, available quantity, position cost, active orders,
  historical orders, and execution evidence are unchanged;
- reserved cash is unchanged; and
- no broker cash-change reason/event, settlement, fee, dividend, funding,
  submit, cancel, retry, reconcile, mandate-dispatch, or execution-lifecycle
  evidence indicates an account mutation.

This is an observational Smoke closeout rule, not a contract, portfolio,
investment, RiskPolicy, or execution rule. It cannot be used to alter
`PortfolioSnapshot` content or hashes, decision inputs, or canonical wire
serialization.

Any economically meaningful difference at the CNY quantum, lifecycle or account
event evidence, a changed reserved-cash value, or an unattributed difference is
still a hard stop. The existing completed S2 cycle, ResearchBundle, decision,
and M2 shadow scorecard remain immutable accepted evidence; closeout must not
rerun S2 or create a replacement cycle.

## 15. Deployment Smoke closeout resume — 2026-08-09

The Owner-approved Section 14 rule was published at DSA
`athena-integration@621a54853448c4f875edc01e6cdc613db149b51f` before this
closeout resumed. No DSA or Athena product code, deployed configuration,
service, scheduler, credential, plist, or runtime process was changed.

### Immutable S2 evidence — revalidated

- The existing completed cycle remains
  `m2-cycle-8438dd415f3ef5ac66eecbc37da7f509893fedb8`, with exactly one
  persisted symbol record for `000977` and duplicate-trigger count `1`.
- Its original authoritative Snapshot A hash remains
  `80c0b2b11a49ea0f7e53e2db0056d647b057f16bf730b1f04a8798db196fe1b9`.
- Its decision remains
  `decision-m2-6c8d4e22ff58fe2e6114fae538300cc94508810d`; its immutable M2
  shadow scorecard hash remains
  `f02ca2d0f0d1b157cdf52d58d7bcf9ea20e7da6c2bda7d93ea181135caed4fa7`.
- The scorecard remains `OFF / NOT_AUTHORIZED`, with no ExecutionMandate,
  ExecutionResult, or PortfolioSnapshot B. The matching persisted analysis and
  single scorecard counts remain unchanged.

### Cash closeout rule — satisfied without canonical mutation

The previously observed `+0.00000000012` available-cash difference was already
attributed to `NUMERIC_REPRESENTATION_JITTER` at the binary64 broker boundary.
It is less than `0.01` CNY and compares equal at the CNY quantum. The recorded
evidence also establishes unchanged reserved cash, position quantity/availability/cost,
active orders, historical orders, executions, equity/nav, and realized PnL, with
no settlement, fee, dividend, funding, cash-event, submit, cancel, retry,
reconcile, mandate-dispatch, or execution-lifecycle evidence. This establishes
Smoke-only zero-mutation semantic equivalence; it did not alter the original or
later canonical snapshot values, hashes, or decision inputs.

### S3 and final safety state — PASS

- The deployed `--webui-only` DSA service remains loopback-only. Local
  `GET /api/v1/single-brain/m2/readiness` returned `200`, reported the existing
  completed cycle, decision, symbol, Athena Runtime portfolio authority, and
  `execution_authorization=OFF`.
- The OpenAPI surface exposes the M2 readiness route as `GET` only. It has no
  mutation, retry, submission, reconciliation, portfolio, or execution-control
  method. `ADMIN_AUTH_ENABLED=false` remains the Owner-approved policy.
- Normal DSA scheduling, P1A shadow wiring, P1B canary, and M2 remain OFF.
  Athena remains `LIVE_TRADING=false`, simulation-only, reconciled, and
  reachable only through the existing loopback path.
- Final read-only evidence retained zero active orders, one historical order,
  one historical execution, and unchanged sanitized trading-evidence digest
  `d576c77542302cf6b23548c5af5f4511cbf165917ef54a3d25892c0537840853`.
  No new mandate, result, Snapshot B, submission, cancellation, retry,
  reconciliation, or portfolio mutation occurred.

Deployment Smoke is complete. This closeout does not authorize recurring M2,
execution, live trading, or any new deployment change.
