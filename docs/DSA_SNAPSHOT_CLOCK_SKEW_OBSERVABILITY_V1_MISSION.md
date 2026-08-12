# DSA Snapshot Clock-Skew Observability v1 — Mission

## Model Mode

- Model: **Terra**
- Reasoning: **Medium / 中**
- Why: this is a narrow observability-only change. It must preserve all existing Snapshot validation, Brain authority, scheduler, RiskPolicy, execution, and trading boundaries while making rejected clock-skew evidence recoverable.

---

# Goal

Implement the smallest possible **Snapshot clock-skew observability** change in DSA.

The purpose is diagnostic only: when an authoritative Athena `PortfolioSnapshot` is accepted or rejected before Brain construction, preserve enough sanitized timing evidence to reconstruct the exact clock-skew decision after the cycle ends.

This mission MUST NOT change validation semantics or make a currently rejected Snapshot pass.

---

# Frozen Semantics

Do not change any of the following:

- `MAX_SNAPSHOT_CLOCK_SKEW = 1s`
- PortfolioSnapshot freshness budget = **300 seconds**
- Snapshot timeout
- retry behavior
- Athena source or code
- scheduler topology or cadence
- RiskPolicy
- Brain / InvestmentDecision semantics
- M3 execution semantics
- execution authority
- BUY/ADD/HOLD capability boundaries
- LIVE / SELL / REDUCE permissions
- auth/network posture
- exact-quantity, UNKNOWN-reconcile, no-blind-retry behavior

No safety gate may be relaxed for this mission.

---

# Required Diagnostic Record

Whenever the authoritative Snapshot is validated in the M2/M3 Single Brain path, persist or otherwise make recoverable a sanitized diagnostic record containing:

- `cycle_id`
- `stage`
  - `initial`
  - `post-research-final-refresh`
- Snapshot `revision`
- Snapshot `as_of`
- Snapshot `created_at`
- DSA `last_response_received_at`
- computed `future_offset_ms`
- Snapshot HTTP/transport elapsed time **only if the existing source already exposes it safely**
- validation result:
  - `accepted`
  - `future-dated`
  - `stale`

For a `future-dated` rejection, these values MUST remain recoverable after the cycle completes or fails closed.

Prefer the smallest existing persistence/read-model extension. Do not introduce a second operational ledger or a broad observability platform.

---

# Privacy / Safety

Do NOT record:

- positions
- quantities
- cash
- account balances
- tokens
- API keys
- credentials
- authorization headers
- complete Snapshot payloads
- unrelated account data

Only the minimum timing/provenance fields above may be persisted/logged.

---

# Failure Semantics

Diagnostic persistence is secondary to safety.

- A `future-dated` Snapshot MUST still fail closed exactly as today.
- A stale Snapshot MUST still fail closed exactly as today.
- A valid Snapshot MUST still be accepted under the existing rules.
- Diagnostic write failure MUST NOT permit Brain or execution to continue when the Snapshot itself is invalid.
- Diagnostic write failure MUST NOT create duplicate decisions, mandates, scorecards, submissions, or retries.
- Do not turn observability failure into a trading-capability change.

If an observability write failure must itself be surfaced, use the smallest non-authoritative diagnostic path available; do not alter investment/execution authority semantics.

---

# Required Tests

Add focused deterministic tests proving:

1. **+0.23s accepted**
   - Snapshot `as_of` is 230 ms ahead of DSA receipt time.
   - Existing validation accepts it.
   - Diagnostic result is `accepted` and `future_offset_ms` is recoverable.

2. **+1.00s boundary unchanged**
   - Preserve the exact current strict comparison semantics.
   - A Snapshot exactly at the current 1-second boundary behaves exactly as before this mission.
   - Test the diagnostic record without changing the decision boundary.

3. **>1s still FAILED_CLOSED**
   - Use a deterministic offset greater than 1 second.
   - Exact existing fail-closed reason remains `authoritative portfolio snapshot is future-dated` or the current canonical equivalent.
   - No Brain decision, scorecard, mandate, dispatch, or broker submission is produced.

4. **Rejected exact skew is recoverable**
   - After a `future-dated` cycle ends, read back the diagnostic evidence and prove the exact test offset is retained together with cycle/stage/revision/timestamps/result.

5. **Diagnostic write failure does not weaken safety**
   - Inject diagnostic persistence/logging failure.
   - Invalid Snapshot still fails closed.
   - No duplicate decision/scorecard/mandate/submission is created.
   - Existing execution behavior is unchanged.

Where practical, cover both `initial` and `post-research-final-refresh` stages, with the primary acceptance requirement on the final pre-Brain refresh because that is the current production blocker.

---

# Scope Boundaries

Expected scope is DSA only and should be minimal.

Do NOT:

- modify Athena
- modify oMLX/Qwen configuration
- tune the model
- change scheduler cadence
- add retries
- widen timeout
- change Snapshot contracts unless strictly necessary for a backward-compatible local diagnostic read-model field
- change Research inputs
- expose account truth to the LLM
- change Brain sizing/allocation
- change M3 coordinator semantics
- enable LIVE
- add SELL/REDUCE
- force a production cycle
- force a broker-simulation mutation

If implementation would require a core contract semantic change or a new cross-repo authority surface, STOP and report an **ARCHITECTURE REVIEW GATE** instead of expanding scope.

---

# Implementation / Validation

1. Inspect the current Snapshot source and M2/M3 validation path at the exact current `athena-integration` base.
2. Implement the smallest recoverable sanitized timing diagnostic.
3. Add focused tests above.
4. Run focused tests first.
5. Run the smallest relevant M2/M3 regression subset needed to prove no safety/identity regression.
6. Run Python compilation and `git diff --check`.
7. Do not run a broad model benchmark, soak, forced scheduler cycle, or broker mutation.
8. Push a branch and open a **Draft PR** against `athena-integration`.
9. Post concise closeout evidence in the PR.
10. STOP for ChatGPT Architecture Review.

---

# Acceptance

PASS only if all are true:

- validation semantics are unchanged;
- 1-second clock-skew rule is unchanged;
- 300-second freshness is unchanged;
- retry/timeout behavior is unchanged;
- rejected future-dated Snapshot exact skew is recoverable after the cycle;
- diagnostic data is sanitized and contains no portfolio/cash/secret payload;
- diagnostic failure cannot weaken fail-closed behavior;
- no Brain/RiskPolicy/scheduler/execution/trading-authority behavior changed;
- focused tests pass;
- Draft PR is opened and no merge/deployment occurs.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine implementation blockers are autonomous: local test fixture updates, repository migration mechanics that do not alter authority semantics, deterministic test plumbing, type/compile issues, and sanitized read-model serialization.

Resolve, verify, and continue without asking the Owner to relay routine logs.

---

# OWNER HARD STOP

Stop if the work would require:

- changing the 1-second clock-skew budget
- changing freshness/timeout/retry policy
- changing RiskPolicy
- changing LIVE/trading permissions
- enabling SELL/REDUCE
- changing broker permissions
- Athena source/deployment changes
- auth/network exposure
- destructive/irreversible migrations
- any decision about accepting previously rejected account truth

---

# Closeout

Report:

- exact base SHA
- exact Draft PR head SHA
- changed files
- persistence/read-model location used
- exact sanitized diagnostic fields
- focused test counts/results
- relevant regression results
- compile / diff-check result
- confirmation that 1s / 300s / timeout / retry / scheduler / RiskPolicy / Brain / execution boundaries are unchanged
- confirmation of no merge/deployment

Then STOP for ChatGPT review.
