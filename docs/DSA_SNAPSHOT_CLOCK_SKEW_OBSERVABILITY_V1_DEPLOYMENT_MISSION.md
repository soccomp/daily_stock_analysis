# DSA Snapshot Clock-Skew Observability v1 — Deployment Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: deployment alignment on M5 must preserve exact reviewed source, runtime safety boundaries, scheduler topology, and simulation-only execution while validating new diagnostics with minimal operational disturbance.

## Authorized Target

Owner has explicitly authorized deployment of PR #14.

**Exact application SHA to deploy:**

`8755b40646b9e653b1edc226f5f3f42d0f839a6d`

This is the merge commit for PR #14 and contains reviewed head:

`4f7e093636fed770afe2c05ee5594a9a2c69ad9f`

This deployment-mission documentation commit is governance only. Do **not** deploy the docs commit in place of the exact application SHA above.

## Goal

Align the M5 DSA runtime to exact application SHA `8755b40646b9e653b1edc226f5f3f42d0f839a6d`, preserve all current Single Brain safety/runtime boundaries, perform the minimum safe smoke, then allow the next natural scheduler cycle to persist sanitized snapshot clock diagnostics.

Do not force a cycle or trade solely for acceptance.

## Frozen Boundaries

Must remain unchanged:

- `com.dsa.webui`
- `main.py --webui-only`
- loopback `127.0.0.1:8080`
- local oMLX text route only
- model `Qwen3-14B-MLX-6bit`
- oMLX loopback/auth posture
- `LIVE_TRADING=false`
- Athena simulation-only
- exactly one `M3_SIMULATION_EXECUTION_ONLY` scheduler
- cadence `3600` seconds
- P1A/P1B OFF
- 1-second `MAX_SNAPSHOT_CLOCK_SKEW`
- 300-second snapshot freshness
- RiskPolicy
- BUY/ADD/HOLD capability only; no SELL/REDUCE expansion
- exact-quantity / UNKNOWN-reconcile / no-blind-retry semantics
- broker permissions
- network/auth exposure
- manual portfolio ledger semantics

No Athena change. No Qwen tuning. No scheduler acceleration.

## Deployment Procedure

1. Record pre-deploy running DSA SHA and sanitized runtime facts.
2. Fetch `origin/athena-integration` and verify exact application commit `8755b406...` exists and contains reviewed PR #14 head `4f7e093...` as a parent.
3. Align the canonical M5 DSA runtime checkout to exact application SHA `8755b406...` using the existing safe deployment method.
4. Preserve all M5-only secrets/configuration. Never print credentials or API keys.
5. Restart/reload only what is required for DSA source alignment. Do not modify/restart Athena or oMLX unless ordinary DSA restart observation requires it.
6. Verify the actual running DSA source resolves to exact application SHA `8755b406...`.

## Minimum Post-Deploy Smoke

Use read-only checks wherever possible and collect sanitized evidence only.

Required:

- `com.dsa.webui` loaded/running
- DSA responds on `127.0.0.1:8080`
- exact running SHA = `8755b40646b9e653b1edc226f5f3f42d0f839a6d`
- local oMLX route/model unchanged
- Athena `READY`
- `LIVE_TRADING=false`
- simulation-only account
- authoritative PortfolioSnapshot readable
- pending reconciliation = 0
- exactly one M3 scheduler at 3600 seconds
- P1A/P1B OFF
- no unexpected broker/order/execution mutation caused by deploy/smoke
- no manual-ledger mutation
- database integrity healthy

Do not rerun the full 94-test suite unless deployment reveals a source/runtime inconsistency.

## Natural-Cycle Diagnostic Acceptance

Do not manually trigger or accelerate the scheduler solely for this mission.

If a natural cycle occurs while observing, report the persisted sanitized clock diagnostics for both stages when present:

- `initial`
- `post-research-final-refresh`

For each diagnostic record report only:

- cycle_id
- stage
- snapshot revision
- `as_of`
- `created_at`
- `last_response_received_at`
- exact `future_offset_ms`
- `transport_elapsed_ms`
- validation result

Also report cycle status, Analyzer duration, whether bounded completion was used, whether Brain produced an InvestmentDecision, mandate/result if naturally applicable, and exact fail-closed reason if any.

Do not expose positions, quantities, cash, balances, secrets, tokens, or complete Snapshot payloads.

If no natural cycle completes during the deployment window, that is not a deployment failure. Report `NATURAL_CYCLE_PENDING` and stop after smoke.

## Acceptance

Deployment PASS requires:

- running DSA exact SHA = `8755b406...`
- launchd/UI healthy on loopback
- Qwen route preserved
- Athena healthy, LIVE false, simulation-only
- scheduler topology/cadence unchanged
- pending reconciliation zero
- no safety/trading capability changes
- no broker/manual-ledger mutation caused by deployment

Natural-cycle diagnostics may remain pending.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine deployment blockers are autonomous: stale local checkout, fetch/alignment, clean DSA restart, launchd reload, port/PID verification, runtime path alignment, read-only smoke, database table creation via the repo's existing non-destructive startup path, and sanitized evidence collection.

Resolve, verify, and continue without asking the Owner to relay routine logs.

## OWNER HARD STOP

Stop if deployment would require:

- LIVE or real-money trading
- SELL/REDUCE expansion
- RiskPolicy changes
- changing the 1-second skew limit
- changing the 300-second freshness rule
- scheduler cadence/topology changes
- auth/network exposure changes
- broker permission changes
- destructive/irreversible migration
- forced broker-simulation mutation
- Athena source/deployment changes affecting execution behavior
- secret rotation/exposure requiring Owner action

## Closeout

Post a concise sanitized deployment closeout to PR #14 containing:

- exact target application SHA
- exact running SHA
- launchd/UI health
- local model route/model identity
- Athena READY/LIVE/simulation facts
- scheduler topology/cadence
- pending reconciliation
- mutation audit
- natural-cycle diagnostic result or `NATURAL_CYCLE_PENDING`
- limitations

Then STOP. No benchmark, soak, tuning, clock-skew policy change, SELL/REDUCE, or unrelated work.
