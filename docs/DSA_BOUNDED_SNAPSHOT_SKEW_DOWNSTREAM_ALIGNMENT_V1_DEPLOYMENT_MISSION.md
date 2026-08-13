# DSA Bounded Snapshot Skew Downstream Alignment v1 — Deployment Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: deployment alignment must preserve exact reviewed source, Single Brain safety boundaries, scheduler topology, and simulation-only execution while validating that the natural Brain path now passes the bounded-skew gate.

## Authorized Target

Owner has explicitly authorized deployment of PR #15.

**Exact application SHA to deploy:**

`f8dcfc6f6ab9f34d141b1f0ccbce3d4b057ea963`

Reviewed PR #15 head contained by this merge commit:

`0ef364050f6f98fb928dde993d889a984a93027a`

This deployment-mission documentation commit is governance only. Do **not** deploy the docs commit in place of the exact application SHA above.

## Goal

Align the canonical M5 DSA runtime to exact application SHA `f8dcfc6f6ab9f34d141b1f0ccbce3d4b057ea963`, perform the minimum safe smoke, then allow the next natural scheduler cycle to verify that an authoritative PortfolioSnapshot within the already-approved 1-second producer-ahead budget reaches downstream Brain validation without the previous false rejection.

Do not force a cycle or trade solely for acceptance.

## Frozen Runtime / Safety Boundaries

Must remain unchanged:

- `com.dsa.webui`
- `main.py --webui-only`
- loopback `127.0.0.1:8080`
- local oMLX text route only
- model `Qwen3-14B-MLX-6bit`
- oMLX loopback/auth posture
- `LIVE_TRADING=false`
- Athena simulation-only
- Athena source/runtime unchanged
- exactly one `M3_SIMULATION_EXECUTION_ONLY` scheduler
- cadence `3600` seconds
- P1A/P1B OFF
- PortfolioSnapshot future-skew budget exactly 1 second
- Snapshot freshness exactly 300 seconds
- Research timestamps remain zero-tolerance
- RiskPolicy unchanged
- BUY/ADD/HOLD capability only; no SELL/REDUCE expansion
- exact-quantity / idempotency / UNKNOWN-reconcile / no-blind-retry semantics
- broker permissions
- auth/network exposure
- manual portfolio ledger semantics

No Qwen tuning. No scheduler acceleration. No threshold changes.

## Deployment Procedure

1. Record pre-deploy running DSA SHA and sanitized runtime facts.
2. Fetch `origin` and verify exact application commit `f8dcfc6f...` exists and contains reviewed head `0ef36405...` as a parent.
3. Align the canonical M5 DSA runtime checkout to exact application SHA `f8dcfc6f6ab9f34d141b1f0ccbce3d4b057ea963` using the existing safe deployment method.
4. Preserve M5-only secrets/configuration. Never print credentials, tokens, or API keys.
5. Restart/reload only what is required for DSA source alignment. Do not modify/restart Athena or oMLX unless ordinary health recovery requires a no-config-change restart.
6. Verify actual running DSA source resolves to the exact application SHA.

## Minimum Post-Deploy Smoke

Required read-only/sanitized checks:

- `com.dsa.webui` loaded/running
- DSA responds on `127.0.0.1:8080`
- exact running SHA = `f8dcfc6f6ab9f34d141b1f0ccbce3d4b057ea963`
- local oMLX route/model unchanged
- Athena READY
- `LIVE_TRADING=false`
- simulation-only account
- authoritative PortfolioSnapshot readable
- pending reconciliation = 0
- exactly one M3 scheduler at 3600 seconds
- P1A/P1B OFF
- database integrity healthy
- no deployment-induced broker/order/execution mutation
- no manual-ledger mutation

Do not rerun the full suite unless deployment reveals a source/runtime inconsistency.

## Natural-Cycle Acceptance

Do not manually trigger or accelerate the scheduler solely for this mission. A normal scheduler run-immediately-on-restart behavior is acceptable because it is existing runtime semantics.

If a natural cycle occurs, follow it through the post-Research final Snapshot refresh and Brain entry.

Report:

- cycle_id
- AnalysisResult success/failure
- Analyzer/Qwen duration
- whether bounded completion/repair was used
- `initial` Snapshot future_offset_ms / validation result
- `post-research-final-refresh` future_offset_ms / validation result
- whether downstream Shadow Wiring accepted the same bounded Snapshot
- whether Decision Engine accepted the authoritative Snapshot
- whether an InvestmentDecision was persisted
- decision action (BUY/ADD/HOLD only if naturally produced)
- mandate count
- dispatch count
- submitted quantity
- exact fail-closed reason if any

Never expose positions, cash, account balances, secrets, or full Snapshot payloads.

### PASS condition for the specific PR #15 fix

If the natural post-Research final Snapshot is within `<= 1 second` producer-ahead skew, downstream DSA must **not** reject it merely because `Snapshot.as_of > now`.

- `<= 1s` PortfolioSnapshot skew: may continue, subject to all other existing checks.
- `> 1s`: must remain fail-closed.
- stale >300s: must remain fail-closed.
- Research future timestamp: remains zero-tolerance.

A later fail-closed for a different valid safety reason is acceptable and should be reported precisely.

If no natural cycle completes during the deployment window, report `NATURAL_CYCLE_PENDING`; that alone is not a deployment failure.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine deployment blockers are autonomous: fetch/alignment, clean DSA restart, launchd reload, loopback port/PID verification, runtime path alignment, additive DB initialization, read-only smoke, and sanitized evidence collection.

Resolve, verify, and continue without asking the Owner to relay routine logs.

## OWNER HARD STOP

Stop if continuing would require:

- LIVE or real-money trading
- SELL/REDUCE expansion
- RiskPolicy changes
- changing the 1-second skew limit
- changing 300-second freshness
- changing Research zero-tolerance
- scheduler cadence/topology changes
- auth/network exposure changes
- broker permission changes
- destructive/irreversible migration
- forced broker-simulation mutation
- Athena source/execution changes
- secret rotation/exposure
- changes in investment or execution authority

## Closeout

Post a concise sanitized deployment closeout to PR #15 containing:

- exact target application SHA
- exact running SHA
- launchd/UI health
- local model route/model identity
- Athena READY/LIVE/simulation facts
- scheduler topology/cadence
- pending reconciliation
- mutation audit
- natural-cycle result or `NATURAL_CYCLE_PENDING`
- bounded-skew downstream validation result
- InvestmentDecision / mandate / dispatch / submission counts if naturally applicable
- confirmation that 1s / 300s / Research zero-tolerance / RiskPolicy / execution boundaries were unchanged
- limitations

Then STOP. No benchmark, soak, tuning, SELL/REDUCE, LIVE, or unrelated work.
