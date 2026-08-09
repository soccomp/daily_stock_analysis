# Single Brain M3 — Autonomous Simulation Trading v1 Mission

**Status date:** 2026-08-09  
**Mission state:** READY TO START  
**Canonical repository:** `soccomp/daily_stock_analysis`  
**Canonical branch:** `athena-integration`

## Recommended Codex mode

**Mode:** Sol  
**Reasoning:** 极高  
**Why:** this mission turns the already-running long-lived Brain into an account-mutating simulation execution loop across DSA and Athena, so exact authority, idempotency, UNKNOWN handling, partial fills, restart recovery, and scorecard lineage must all hold simultaneously.

---

# 1. Mission Goal

Complete one end-to-end outcome:

> **Keep the Single Brain architecture unchanged while allowing the continuously running DSA Brain to autonomously execute valid BUY / ADD decisions through Athena in the simulation account, reconcile broker truth, obtain authoritative Snapshot B, and close the same Decision Scorecard.**

The target runtime flow is:

```text
Athena authoritative account facts
        ↓
DSA Research
        ↓
ResearchBundle
        ↓
DSA Brain
        ↓
InvestmentDecision
        ↓
exact ExecutionMandate
        ↓
Athena execution safety kernel
        ↓
simulation broker
        ↓
ExecutionResult
        ↓
authoritative PortfolioSnapshot B
        ↓
DSA Brain / Single Decision Scorecard
```

This is **one Mission**. Diagnosis, implementation, testing, cross-repository integration, deployment preparation, canary, reconciliation, restart recovery, and closeout are internal steps of this Mission. Do not split them into separate Owner-managed missions unless a genuine governance boundary requires it.

This Mission inherits **Autonomous Mission Execution Policy v1.0**.

---

# 2. Starting State

The accepted deployed baseline is:

- `M2 CONTINUOUS SHADOW OPERATIONS PASS`
- DSA recurring M2 Shadow is ON
- exactly one `M2_SHADOW_ONLY` scheduler authority
- accepted cadence is 3600 seconds
- DSA remains loopback-only under `--webui-only`
- DSA is the only investment decision authority
- Athena is the authoritative factual account-state producer
- Athena is simulation-only
- `LIVE_TRADING=false`
- execution authorization is currently OFF
- P1A and P1B remain OFF
- continuous M2 naturally produces ResearchBundle → InvestmentDecision → DecisionSignal → Shadow Scorecard
- the accepted P0/P1 foundation already proves a bounded BUY/ADD exact-quantity simulation vertical slice
- Athena may execute the exact mandate quantity or block; it may not resize or reinterpret
- UNKNOWN requires broker reconciliation before any retry decision
- partial-fill remainder is never automatically resubmitted
- one `decision_id` links the decision lifecycle and Single Decision Scorecard

M3 turns those accepted foundations into one production-quality autonomous simulation execution loop.

---

# 3. Authority Constitution — Immutable

The following are not implementation preferences. They are architecture invariants.

> **研究层拥有解释权，决策层拥有资本配置权，执行层拥有操作权但没有投资判断权。**

> **研究层判断资产，不判断账户该怎么动。**

> **DSA 管目标状态，Athena 管事实状态。**

> **交易层可以说“执行不了”，不能说“我不同意”。**

Therefore:

- Research has no capital-allocation authority.
- DSA Brain is the only investment decision authority.
- Final quantity lives only in `InvestmentDecision`.
- `ExecutionMandate` is a deterministic machine projection of the accepted `InvestmentDecision`.
- Athena has execution authority but no investment judgment.
- Athena may execute exactly or BLOCK/REJECT/EXPIRE/UNKNOWN; it may never resize, substitute, reinterpret, or improve the investment decision.

Forbidden example:

```text
Brain quantity = 500
Athena decides 300 is safer
```

That behavior is an architecture failure.

---

# 4. M3 Product Scope

Executable investment actions in M3:

```text
BUY
ADD
HOLD
```

- `HOLD` emits no mandate.
- BUY/ADD may execute only when all execution gates are explicitly satisfied.
- SELL/REDUCE execution is **not** introduced or activated in this Mission.
- Automated stop-loss / take-profit is not introduced or activated.
- Existing dormant or experimental exit functionality must not be opportunistically enabled.

SELL/REDUCE and exit lifecycle are a later governed capability because they introduce a distinct investment lifecycle, not because this Mission should be artificially fragmented.

---

# 5. Operating Modes

The runtime must expose a clear, fail-closed distinction between at least:

```text
SHADOW
SIMULATION_EXECUTION
```

Default remains safe.

A configuration accident must never silently convert SHADOW into execution.

Simulation execution requires all applicable explicit conditions to agree, including at minimum:

```text
LIVE_TRADING == false
simulation_only == true
execution mode == SIMULATION_EXECUTION
execution authorization == ON for this simulation path
authoritative Snapshot A valid and fresh
InvestmentDecision valid
ExecutionMandate valid
```

If any required condition is absent, contradictory, stale, malformed, or unprovable, fail closed.

Do not weaken the existing passwordless local-only product policy. Do not broaden network exposure, credentials, trust boundaries, or broker permissions.

---

# 6. Exact Decision → Mandate → Broker Rule

For an executable BUY/ADD decision:

```text
InvestmentDecision.quantity
        ==
ExecutionMandate.quantity
        ==
submitted broker quantity
```

The only alternative is zero submitted quantity because execution was BLOCKED/REJECTED/etc.

Athena may perform operational safety checks such as:

- duplicate/replay/idempotency
- account/environment identity
- simulation-only / `LIVE_TRADING=false`
- stale decision or snapshot
- insufficient actual cash
- lot/tick/session/suspension constraints
- malformed/conflicting command
- broker readiness/rejection/network uncertainty

Athena must not perform portfolio sizing or investment reinterpretation.

If the exact decision cannot be executed, return execution facts to the Brain and require a new Brain decision when appropriate.

---

# 7. End-to-End Idempotency and Replay Safety

Prove durable idempotency across:

```text
decision_id
mandate_id
broker request identity
ExecutionResult
Single Decision Scorecard
```

The following must not create duplicate orders:

- duplicate scheduler invocation
- repeated HTTP request
- DSA restart
- Athena restart
- timeout
- delayed broker response
- network uncertainty
- process crash after submit but before local acknowledgement
- replay of an already-consumed mandate

Use persisted execution identity/state where required. Do not rely only on in-memory locks for broker mutation safety.

---

# 8. UNKNOWN Semantics

UNKNOWN is not a retry signal.

Required behavior:

```text
submission outcome uncertain
        ↓
UNKNOWN
        ↓
reconcile broker truth first
        ↓
return factual ExecutionResult / current account state
        ↓
Brain decides any next action
```

Never blind-resubmit an UNKNOWN mandate.

If the existing infrastructure cannot conclusively reconcile an UNKNOWN state, fail closed and expose the unresolved state. Do not manufacture certainty.

---

# 9. Partial Fill Semantics

Required example:

```text
Mandate = BUY 500
broker fills 300
remainder later cancelled or expires
```

The system must record the factual lifecycle and must **not** automatically submit another 200.

The next possible order must come from:

```text
new authoritative PortfolioSnapshot
        ↓
DSA Brain re-decision
        ↓
new InvestmentDecision
        ↓
new mandate if authorized
```

Execution may report facts. Only the Brain may authorize capital allocation.

---

# 10. Portfolio Truth and Snapshot B

Athena/Broker remains the factual portfolio authority.

After an order lifecycle materially changes account state, M3 must obtain a new authoritative `PortfolioSnapshot` as Snapshot B.

DSA must not replace Athena truth with a synthetic post-trade portfolio calculation.

The final scorecard lineage for an executable decision must connect:

```text
ResearchBundle
PortfolioSnapshot A
RiskPolicy
InvestmentDecision
ExecutionMandate
ExecutionResult
PortfolioSnapshot B
```

using the same `decision_id` lineage.

Canonical snapshot values, hashes, producer ownership, revision/supersession rules, and accepted clock-skew semantics remain unchanged.

---

# 11. Continuous Autonomous Operation

The completed M3 system must not depend on a manual one-shot production command.

Once explicitly activated after review, the existing long-running DSA Brain loop must be able to reach simulation execution autonomously when the Brain naturally produces a valid BUY/ADD decision.

Do **not** force the production Brain to BUY/ADD merely to satisfy a canary.

Use deterministic/replay/integration tests for action-specific coverage. Production behavior must remain a genuine Brain decision.

---

# 12. Codex Engineering Authority

Within this Mission and its safety envelope, Codex is authorized to autonomously:

- inspect both DSA and Athena accepted baselines
- create fresh branches/worktrees
- modify DSA implementation
- modify Athena implementation where required by the already-approved execution contract
- add/update tests
- add bounded persistence required for idempotency/audit/recovery
- improve readiness and operator observability
- repair implementation defects
- resolve deployment compatibility issues
- run focused and full regression suites
- run architecture-boundary tests
- run cross-repository tests
- prepare sanitized evidence
- create/update Draft PRs
- prepare deployment and rollback plans
- continue through ordinary blockers without returning to the Owner

Do not modify Athena merely for convenience if the required behavior can correctly remain DSA-side.

No automatic merge is authorized before the planned review gate below.

---

# 13. Required Engineering Proof Before Human Gate

Codex chooses the detailed implementation sequence, but before the planned gate it must have reviewable evidence for at least:

- exact Brain quantity → mandate quantity → broker submission quantity
- HOLD → no mandate
- BUY/ADD only; SELL/REDUCE unreachable in M3 activation
- default execution OFF
- explicit simulation-execution enablement
- `LIVE_TRADING=false` fail-closed behavior
- authoritative Snapshot A validation
- mandate schema/hash/lineage validation
- duplicate mandate rejection/deduplication
- restart replay safety
- crash/timeout recovery
- UNKNOWN reconciliation with no blind retry
- partial fill with no automatic remainder resubmit
- broker rejection handling
- expired/cancelled lifecycle handling where applicable
- authoritative Snapshot B after account mutation
- one Decision Scorecard with complete lineage
- no Athena resizing or investment judgment
- continuous scheduler integration without duplicate execution authority
- shared analysis/decision ownership remains coherent
- architecture boundary tests
- DSA full regression
- Athena full regression
- cross-repository regression
- rollback plan
- dry-run/non-mutating deployed preflight where safely possible

Do not artificially shorten production cadence just to make tests fast.

---

# 14. The One Planned Human Gate

There is one planned Owner-visible gate in this Mission:

> **`M3 SIMULATION EXECUTION REVIEW GATE`**

Stop here **before the first broker-mutating simulation order in the running deployment**.

By this point, Codex should already have done the maximum safe autonomous work: implementation, tests, Draft PRs, architecture proof, cross-repository proof, non-mutating deployment verification where applicable, and exact deployment/rollback preparation.

At this gate provide a concise review packet containing:

- DSA PR number/head SHA
- Athena PR number/head SHA if Athena changed
- exact files changed
- old vs new runtime execution semantics
- exact mode/authorization gates
- proof of exact-quantity semantics
- duplicate/replay/UNKNOWN/partial-fill/restart proof
- focused + full test results
- architecture-test results
- deployment plan
- rollback plan
- residual risks

ChatGPT performs architecture/code review.

The Owner decision should be reduced to one clear question:

> **Approve or do not approve the first simulation-account mutation and activation of `SIMULATION_EXECUTION`.**

Do not create a separate canary/deployment/activation Mission at this point.

---

# 15. After Gate Approval — Continue the Same Mission

If review and Owner authorization are recorded, continue this same Mission autonomously through:

```text
merge approved PR(s)
→ controlled DSA/Athena deployment as required
→ verify execution still OFF
→ explicitly enable SIMULATION_EXECUTION
→ controlled first production simulation canary
→ broker-truth reconciliation
→ ExecutionResult
→ authoritative Snapshot B
→ Scorecard closeout
→ restart/recovery proof
→ continuous scheduler proof
→ zero-live-risk safety closeout
```

Do not split those steps into separate missions.

---

# 16. First Production Simulation Canary

Before any mutation, prove:

- correct simulation account identity
- Athena `LIVE_TRADING=false`
- Athena simulation-only
- accepted code provenance
- DSA remains Brain authority
- exact one active scheduler/execution authority
- no stale or previously consumed mandate can fire
- SELL/REDUCE disabled
- automated exits disabled
- rollback available
- execution mode explicitly authorized

The canary may execute only a genuine, valid Brain-authorized BUY/ADD decision.

Do not forge an `InvestmentDecision` in production merely to create an order.

If the natural Brain decision is HOLD, the system should HOLD. A deterministic non-production test already proves BUY/ADD behavior; production must not be manipulated for optics.

---

# 17. Scorecard Acceptance

For an executed simulation decision, the final Single Decision Scorecard must make it possible to answer:

1. What was the authoritative account state before the decision?
2. What research did DSA use?
3. Why did the Brain decide BUY/ADD?
4. What exact final quantity did the Brain authorize?
5. What exact mandate did Athena receive?
6. What did the broker actually accept/fill/reject?
7. What authoritative account state existed afterwards?
8. Did execution match the Brain decision exactly?

One Decision ID. One final scorecard.

Research/sizing/data/execution diagnostics may be attached, but do not create a second competing investment scorecard.

---

# 18. M3 Safety Closeout

Terminal PASS requires evidence that:

- DSA remains the only investment decision authority
- Athena remains execution-only
- `LIVE_TRADING=false`
- simulation account only
- BUY/ADD/HOLD only
- SELL/REDUCE remains disabled
- automated stops remain disabled
- no hidden resizing
- no duplicate orders
- no blind UNKNOWN retry
- no automatic partial-fill remainder resubmit
- Snapshot B is authoritative Athena truth
- decision/mandate/result/snapshots are lineage-linked
- one Decision Scorecard closes the lifecycle
- restart recovery is safe
- long-running autonomous scheduling remains healthy
- broker/order/execution/account evidence reconciles
- no credential/network/auth expansion occurred

---

# 19. Autonomous Blockers — Resolve and Continue

The following are normally **not** terminal gates:

- unit/integration test failures
- broker response-shape mismatch
- serialization bugs
- local deployment-path mismatch
- reversible configuration mistakes
- scorecard persistence bugs
- idempotency implementation defects
- scheduler/restart/recovery defects
- readiness/observability defects
- timeout handling defects
- ordinary cross-repository integration defects

Use, if useful:

```text
AUTONOMOUS BLOCKER — INVESTIGATING
```

then:

```text
AUTONOMOUS BLOCKER — RESOLVED AND CONTINUING
```

Do not return the Mission to the Owner merely because a code change or additional test is required.

---

# 20. Architecture Review Escalation

An additional architecture review gate is justified only if resolving the issue requires materially changing an accepted invariant such as:

- Single Brain authority
- six canonical contracts
- final quantity ownership
- PortfolioSnapshot authority/semantics
- exact execution semantics
- UNKNOWN semantics
- partial-fill semantics
- Decision ID / scorecard identity model
- persistence ownership across DSA/Athena

Before escalating, complete the maximum safe diagnosis/design/implementation/test work so the review is concrete rather than speculative.

---

# 21. OWNER HARD STOP

Use `OWNER HARD STOP` only when the next action genuinely requires Owner authority, for example:

- Live trading
- real money
- broker permission expansion
- enabling SELL/REDUCE
- automated exit authority
- material RiskPolicy product change
- changing investment authority
- weakening exact execution
- authentication/network/trust-boundary expansion
- destructive/irreversible data migration
- another material product/risk choice not already governed

Return:

```text
OWNER HARD STOP: <smallest specific decision required>
```

Do not use Owner HARD STOP for ordinary engineering inconvenience.

---

# 22. GitHub and Evidence Rules

GitHub is the canonical shared fact layer.

Codex should publish sanitized mission evidence to the relevant M3 PR(s) and/or canonical governance docs so ChatGPT can independently verify status without the Owner copying terminal logs.

Do not publish:

- credentials
- cookies/tokens
- account identifiers
- raw sensitive broker payloads
- secrets

PR merges require explicit authorization at the planned review gate. After that authorization, the same Mission may continue through the approved merge/deploy/activation envelope without creating new Owner round-trips for routine steps.

---

# 23. Terminal State

Return exactly one terminal Mission state:

```text
M3 AUTONOMOUS SIMULATION TRADING V1 PASS
```

or, only when genuinely required:

```text
OWNER HARD STOP: <specific decision>
```

Do not terminate the Mission on an ordinary implementation blocker.
