# DSA Research → Brain HOLD Semantics v1 — Deployment Mission

## Model Mode
- Model: **Terra**
- Reasoning: **Medium / 中**
- Escalate only if deployment reveals a source-of-truth, authority, or safety-semantic conflict.

## Exact Deployment Target
- Repository: `soccomp/daily_stock_analysis`
- PR: #16
- Reviewed PR head: `f94ed46ecba0fc322ae50e683e470faa10afa4fd`
- **Runtime target SHA: `8d538348d4ca9c4633a978f318faf9402119aaab`**
- This deployment mission is a later docs-only governance commit. **Do not deploy the docs commit.**

## Owner Authorization
The Owner explicitly authorized deployment after PR #16 Architecture Review PASS / MERGE-READY and merge.

## Goal
Deploy M5 DSA to the exact approved merge commit and verify that runtime safety/configuration remains unchanged. Validate the Research → Brain HOLD semantics only from normal smoke/runtime evidence; do not create artificial trading activity.

## Deployment Steps
1. Verify GitHub `athena-integration` contains exact target `8d538348d4ca9c4633a978f318faf9402119aaab` and that it contains reviewed head `f94ed46e...`.
2. On M5, record current DSA SHA and a reversible pre-deploy ref/state.
3. Sync the DSA application worktree to exact target SHA `8d538348d4ca9c4633a978f318faf9402119aaab` using the existing deployment procedure.
4. Do not modify source, `.env`, launchd plist, scheduler cadence, Qwen/oMLX config, Bocha/search config, Athena, RiskPolicy, broker permissions, auth/network scope, or trading capability.
5. Restart only what the existing DSA deployment procedure requires.
6. Verify DSA web service health on the existing loopback binding and verify runtime reports the exact target SHA.

## Required Runtime Safety Checks
Confirm after deployment:
- DSA remains `main.py --webui-only` on existing loopback UI binding.
- Local generation route remains the existing Qwen/oMLX route; do not tune or switch models.
- Athena remains READY/read-only authority source for PortfolioSnapshot; no Athena source/config change.
- `LIVE_TRADING=false` and simulation-only behavior remain unchanged.
- Exactly the existing single `M3_SIMULATION_EXECUTION_ONLY` scheduler remains at 3600 seconds; no duplicate scheduler.
- P1A/P1B remain OFF.
- pending reconciliation is 0 unless pre-existing factual state proves otherwise; do not clear/mutate it just to satisfy the check.
- no deployment-induced mandate, dispatch, broker submission, cancel, retry, manual-ledger mutation, or Athena account mutation.
- SELL/REDUCE remains unsupported; no capability expansion.

## PR #16 Semantic Smoke
Use deterministic/read-only smoke or existing test/runtime state to confirm:
- non-actionable `watch/hold/avoid/alert` semantics can form canonical HOLD with zero delta and no execution price plan;
- `reduce/sell` and missing/ambiguous/unrecognized actions fail closed;
- BUY/ADD still require valid executable plans;
- HOLD cannot project an ExecutionMandate.

Do **not** invoke a new Qwen/Bocha request solely for smoke. Do not force a scheduler cycle or broker-simulation trade.

## Natural Cycle Handling
If the normal service restart causes the existing scheduler's ordinary immediate-on-restart natural cycle, observe it; do not cancel it and do not trigger an additional cycle.

If such a natural cycle completes within the deployment window, report:
- cycle id and final state;
- Research structured action;
- whether final authoritative Snapshot refresh passed;
- whether canonical InvestmentDecision was persisted and its action;
- mandate / dispatch / submitted quantity / ExecutionResult counts;
- exact fail-closed reason if any.

If Research returns `watch/hold/avoid/alert`, the desired proof is canonical `HOLD`, `delta_quantity=0`, zero execution artifacts even when raw Research sniper prices are non-executable.

If Research returns `buy/add`, do not force an outcome; existing plan/RiskPolicy/Brain gates decide naturally.

If no natural cycle completes promptly, **do not wait up to the 3600-second cadence and do not force one**. Close deployment as `DEPLOYED / SMOKE PASS — NATURAL_CYCLE_PENDING` if all deployment checks pass.

## Frozen Boundaries
No changes to:
- PortfolioSnapshot authority, 1-second skew budget, 300-second freshness, canonical hash/content;
- Research timestamp semantics;
- RiskPolicy or sizing formulas;
- scheduler cadence/topology;
- Qwen/oMLX or Bocha/search provider configuration;
- execution idempotency, exact quantity, UNKNOWN reconciliation-before-retry, partial-fill behavior;
- Athena, broker permissions, auth/network exposure;
- LIVE state;
- BUY/ADD/HOLD capability boundary; no SELL/REDUCE.

## Stop Conditions
Stop and report before proceeding if exact SHA cannot be established, runtime would require unapproved config/source changes, or any deployment action would expand trading/security authority.

Routine local deployment blockers such as a transient port handoff may be resolved using the existing unchanged deployment procedure, then continue.

## Closeout
Post a deployment closeout on PR #16 with:
- exact running SHA;
- health/safety checks;
- smoke result;
- natural-cycle evidence if one naturally occurred;
- confirmation of zero unauthorized mutations/capability changes.

Final disposition must be one of:
- `DEPLOYED / SMOKE PASS`
- `DEPLOYED / SMOKE PASS — NATURAL_CYCLE_PENDING`
- `DEPLOYMENT BLOCKED — <reason>`

STOP after closeout. Do not begin another mission.