# DSA Local LLM Latency Alignment v1 — Codex Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a narrow but safety-sensitive DSA control-flow alignment around authoritative account truth and decision timing. It requires preserving Single Brain invariants and M3 idempotency, but it is not a broad cross-repo architecture redesign.

---

# Mission Name

**Local LLM Latency Alignment v1：Research 成功后、Brain 决策前重新获取最新 Athena authoritative PortfolioSnapshot，消除本地 LLM 长延迟导致的 Snapshot A 过期问题。**

## Canonical Source

Repository: `soccomp/daily_stock_analysis`

Target integration branch: `athena-integration`

Exact `athena-integration` base verified at mission authoring:

`d1ce915c47b4ca0e408ed3cdd7e4d5ffb98d6637`

That base already contains the quota-saving local oMLX/Qwen3 Phase A mission. This mission is intentionally separate: **do not turn it into another local-model benchmark or oMLX tuning task.**

Create a dedicated implementation branch from the latest exact `origin/athena-integration`, preferably:

`fix/local-llm-latency-alignment-v1`

Record the actual base SHA before implementation. If `athena-integration` has advanced beyond the SHA above, use the new exact head and report it; do not reset or rewrite integration history.

---

# Problem Statement

The current DSA decision wiring enforces the correct safety invariant: authoritative `PortfolioSnapshot` must be no more than five minutes old at the time the Brain uses it.

Current `InvestmentShadowWiringService` has:

- `MAX_SNAPSHOT_AGE = timedelta(minutes=5)`
- validation that rejects an authoritative snapshot when `now - portfolio_snapshot.as_of > MAX_SNAPSHOT_AGE`
- `InvestmentDecisionEngine().decide(...)` consuming the injected `portfolio_snapshot`

This safety rule is correct and must remain unchanged.

The problem is timing. A local LLM can spend enough time completing Research/Analyzer work that a snapshot acquired earlier in the cycle is fresh when research starts but stale by the time `InvestmentDecisionEngine` consumes it. The correct repair is **not** to widen the freshness window. The correct repair is to reacquire authoritative account truth at the final Research → Brain boundary.

Single Brain doctrine remains:

> Research decides what the asset evidence means. DSA Brain decides the target state. Athena supplies authoritative account truth and owns execution/safety infrastructure.

Research must not own account allocation truth, and the execution layer must not reinterpret the Brain decision.

---

# Goal

After a successful Research/Analysis result exists, but immediately before DSA creates the account-aware `InvestmentDecision`, obtain the latest Athena authoritative `PortfolioSnapshot` and use **that refreshed snapshot** as Snapshot A for:

- freshness/authority validation
- RiskPolicy account applicability checks
- position/cash/exposure-aware sizing
- `InvestmentDecisionEngine`
- downstream DecisionSignal / scorecard lineage
- any eventual M3 `ExecutionMandate` execution precondition that references Snapshot A

The refreshed snapshot must be the single authoritative pre-decision account fact for that decision.

If the final refresh cannot produce a valid fresh authoritative snapshot, fail closed. Do not create an actionable decision from stale account truth, do not create/dispatch a mandate, and do not attempt a broker operation.

---

# Frozen Safety Boundaries

This mission MUST NOT change any of the following:

- the five-minute / 300-second snapshot freshness requirement
- `PortfolioSnapshot` authority semantics
- RiskPolicy semantics or values
- sizing formulas or target quantity semantics
- exact-quantity execution invariant
- M3 BUY/ADD/HOLD action boundary
- SELL or REDUCE capability
- LIVE trading capability or `LIVE_TRADING=false`
- simulation-only execution mode
- execution authorization
- broker permissions
- scheduler mode or cadence
- Athena source, deployment, or broker-side behavior
- manual portfolio ledger semantics
- network binding, API authentication, or security exposure
- oMLX model, quantization, context window, parser, profiles, concurrency, KV cache, speculative decoding, or other model/runtime tuning
- current cloud/local provider architecture except where a minimal test fixture is required to reproduce latency

No forced BUY/ADD. No forced trade. No scheduler acceleration. No broker mutation for acceptance testing.

This is a **DSA-only control-flow correction**.

---

# Architecture Invariant

The final pre-decision sequence must conceptually be:

```text
Research / Analyzer completes successfully
        ↓
ResearchBundle can be constructed
        ↓
FINAL authoritative Athena PortfolioSnapshot refresh
        ↓
validate snapshot authority + age + account identity
        ↓
validate RiskPolicy against refreshed account truth
        ↓
InvestmentDecisionEngine
        ↓
Decision / Scorecard / optional M3 projection
```

Do not move portfolio/account authority into Research.

Do not make the LLM call Athena.

Do not let Research import broker, execution, portfolio mutation, RiskPolicy gate, or sizing authority.

Do not synthesize a snapshot from pre-research holdings plus assumed deltas.

---

# Required Behavior

## 1. Refresh at the last responsible moment

Identify the real production M2/M3 orchestration path that currently obtains/injects `PortfolioSnapshot` into `InvestmentShadowWiringService.build_from_analysis(...)` or its equivalent decision-building path.

Place the authoritative refresh **after successful analysis/research completion and as close as practical before the Brain decision boundary**.

Prefer changing the orchestration/caller ownership of snapshot acquisition rather than weakening `InvestmentShadowWiringService` validation.

If a clean design requires the wiring service to accept a snapshot provider/callback instead of a pre-fetched snapshot, that is an **ARCHITECTURE REVIEW GATE** because it changes a core interface. Stop before broadening the contract and present the smallest proposed interface change with rationale.

## 2. Use the refreshed snapshot, not the earlier one

If an earlier snapshot exists for cycle setup, display, watchlist selection, or non-authoritative context, it may remain for those bounded purposes. It must not silently remain the account truth used for final sizing/decision once Research has completed.

The final decision must reference the refreshed Snapshot A identity/revision/content hash.

If the refreshed snapshot differs from the earlier snapshot because cash, positions, orders, or revision changed, **use the refreshed truth**. Do not require equality with the earlier snapshot and do not overwrite Athena truth with DSA assumptions.

## 3. Preserve fail-closed behavior

If final snapshot acquisition:

- fails
- times out
- returns an invalid contract
- returns a future-dated snapshot
- returns a snapshot older than the existing five-minute bound
- returns the wrong authoritative account
- conflicts with RiskPolicy applicability

then fail closed with a specific safe reason.

No actionable `InvestmentDecision` may be produced from stale account truth. No `ExecutionMandate` or broker submit/cancel may occur from that failed path.

Do not map ordinary Research failure to Snapshot failure or vice versa; preserve reason explainability.

## 4. Preserve lineage and idempotency

A refresh must not create duplicate decisions, mandates, submissions, or scorecards.

Existing decision-cycle / decision-id / mandate-id idempotency behavior remains authoritative.

If identity derivation currently includes Snapshot A content hash, ensure the implementation remains deterministic and safe when the final refreshed snapshot is newer than a pre-research snapshot. Do not invent a retry loop that can generate multiple decisions simply because snapshot revision advances.

The persisted M3 lineage must continue to treat the final refreshed authoritative snapshot as `portfolio_snapshot_a`.

## 5. No new execution semantics

`M3SimulationExecutionCoordinator` remains an execution consumer of an already-created Brain decision. It must not fetch a newer snapshot and resize/reinterpret the decision itself.

Execution may continue to block/reconcile under its existing operational rules. This mission does not move capital-allocation logic downstream.

---

# Quota-Saving Implementation Discipline

The Owner's Codex quota is scarce. Keep this mission narrow.

Do NOT perform:

- broad repository refactors
- full historical LLM replay
- local-model quality benchmarking
- long soak tests
- full cross-repo test matrices
- oMLX tuning
- dependency upgrades unless an unavoidable focused test blocker proves one is required
- unrelated lint/style cleanup
- UI redesign
- Athena changes

First inspect only the direct production caller(s), authoritative snapshot adapter/client, `src/investment/shadow_wiring.py`, M2/M3 orchestration/repository surfaces, and their focused tests.

Make the smallest coherent change that puts the refresh at the correct authority boundary.

---

# Required Tests

Use deterministic mocks/fakes. Acceptance must not depend on waiting five real minutes and must not hit a real broker.

At minimum add focused coverage for all of these cases:

### Case A — Research latency makes the original snapshot stale; final refresh is fresh

1. Initial/pre-research snapshot is valid at cycle start.
2. Simulated Research latency advances the decision clock beyond 300 seconds from that old snapshot.
3. Final Athena refresh returns a fresh authoritative snapshot.
4. Decision succeeds.
5. Assert `InvestmentDecisionEngine` / resulting decision lineage used the **fresh refreshed snapshot revision/hash**, not the old one.

This is the principal regression test.

### Case B — Final refresh is also stale or unavailable

1. Research succeeds.
2. Final snapshot refresh fails or returns stale authority truth.
3. Path fails closed with a specific reason.
4. Assert zero actionable mandate creation and zero execution transport/broker calls.

### Case C — Account truth changes during Research

1. Pre-research snapshot contains one cash/position state.
2. Final refreshed snapshot has a newer revision and materially changed cash/position state.
3. Assert decision/sizing uses only the refreshed state.
4. Assert persisted Snapshot A lineage matches the refreshed authoritative snapshot.

### Case D — Idempotency remains intact

Exercise the relevant repeated/recovery path and prove that refreshing authoritative truth does not create duplicate decision IDs, mandates, submissions, or scorecards.

### Case E — Existing five-minute rejection remains intact

Keep or add a direct focused test proving `InvestmentShadowWiringService` still rejects a snapshot older than `MAX_SNAPSHOT_AGE`.

**Do not modify the test to expect a longer freshness window.**

---

# Focused Validation Only

Run the smallest directly relevant suite, including existing tests for:

- snapshot authority/freshness
- shadow wiring / decision engine boundary
- M2/M3 production orchestration path touched by the change
- M3 idempotency / no-retry semantics if affected
- scorecard Snapshot A lineage if affected

Run broader tests only if the changed files make them necessary or a focused failure points to a wider regression.

Report exact commands and pass/fail counts.

Known unrelated/pre-existing failures must be identified as such; do not spend quota repairing unrelated failures under this mission.

---

# Sanitized Runtime Evidence

If a safe local DSA smoke can be performed without triggering a production autonomous cycle, collect one sanitized trace proving the order:

```text
research_completed_at
→ final_authoritative_snapshot_fetch_at
→ refreshed_snapshot_as_of / revision or safe hash prefix
→ brain_decision_created_at
```

Do not expose holdings, account identifiers, API keys, broker credentials, prompts containing private portfolio data, or raw private account payloads in GitHub evidence.

If obtaining runtime evidence would require forcing M3, changing cadence, or causing broker-simulation mutation, skip it and rely on deterministic tests. State the limitation.

---

# Architecture Review Gate

Stop and request ChatGPT Architecture Review before proceeding if the minimal fix requires any of these:

- changing the `PortfolioSnapshot` contract or authority semantics
- changing RiskPolicy semantics
- changing `InvestmentDecisionEngine` input semantics
- moving snapshot acquisition into Research/LLM code
- moving sizing/decision authority into Athena or Execution
- changing `InvestmentShadowWiringService.build_from_analysis(...)` public/core interface in a non-trivial way
- introducing a new cross-layer dependency
- changing decision/mandate identity semantics beyond the smallest safe compatibility adjustment

Routine orchestration wiring, dependency injection in local composition roots, focused tests, logging/evidence, and reversible local setup are autonomous unless they cross one of the gates above.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine blockers are not hard stops. Diagnose, fix, test, and continue for:

- branch/worktree setup
- focused fixture construction
- test clock/fake snapshot provider setup
- local import/type/test failures caused by the implementation
- reversible test configuration
- safe sanitized instrumentation
- stale local checkout alignment to the exact branch base

Do not ask the Owner to relay logs or copy/paste routine information that Codex can inspect itself.

---

# OWNER HARD STOP

Stop and ask the Owner only if the implementation would require:

- LIVE trading or real-money capability
- SELL/REDUCE capability
- changing investment authority
- changing RiskPolicy choices/limits
- changing broker permissions
- changing scheduler cadence to induce a cycle
- changing network exposure or authentication/security posture
- destructive/irreversible migration
- Athena deployment/source changes that alter execution behavior
- forced broker-simulation mutation for acceptance
- any ambiguous safety boundary that materially expands trading capability

---

# Deliverables

1. Dedicated implementation branch from exact latest `origin/athena-integration`.
2. Minimal source change implementing final pre-Brain authoritative Snapshot A refresh.
3. Focused regression tests covering Cases A–E.
4. Sanitized evidence showing the new temporal ordering and proving no stale sizing.
5. A **Draft PR** targeting `athena-integration`.
6. PR body must include:
   - exact base SHA
   - exact final HEAD SHA
   - concise root cause
   - files changed
   - test commands/results
   - proof that the 300-second freshness rule remains unchanged
   - proof that Athena/RiskPolicy/scheduler/execution authorization/LIVE/SELL/REDUCE/oMLX tuning were not changed
   - any remaining limitations
7. Codex closeout comment with the same canonical evidence.

---

# Acceptance Criteria

PASS only if all are true:

- Research may take longer than the snapshot freshness window without causing a decision to use stale account truth, provided a fresh authoritative Athena snapshot is available at the final boundary.
- The five-minute / 300-second freshness invariant is unchanged.
- `InvestmentDecisionEngine` consumes the refreshed authoritative Snapshot A.
- Changed holdings/cash/revision during Research are reflected in the final Brain decision.
- Final refresh failure/staleness fails closed.
- No duplicate decision/mandate/submission/scorecard behavior is introduced.
- M3 execution still executes exactly or blocks/reconciles; it does not resize or reinterpret.
- No Athena, RiskPolicy, scheduler cadence, execution authorization, LIVE, SELL/REDUCE, network/auth, manual-ledger, or oMLX tuning change occurs.
- Focused tests pass.
- A Draft PR with sanitized evidence exists.

---

# Final Stop Condition

When the focused implementation, tests, evidence, and Draft PR are complete, **STOP**.

Do not merge.

Do not deploy to M5.

Do not start another oMLX optimization/benchmark phase.

ChatGPT Architecture Review is the next gate.