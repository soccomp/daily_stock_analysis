# DSA Daily Overview v1 — M5 Deployment Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a deployment-alignment mission across Git SHA, M5 launchd/runtime, built frontend assets, real connected-account facts, Single Brain readiness, and read-only UI smoke. It does not authorize a new architecture or trading capability.

---

## Authorization

Owner has explicitly authorized deployment of PR #11 to M5.

This mission authorizes deployment and verification only.

It does **not** authorize:

- new product/source changes
- a new source PR merge
- Athena changes
- RiskPolicy changes
- SELL / REDUCE
- LIVE trading
- auth/network exposure expansion
- scheduler cadence changes
- forced analysis or forced trades

---

## Fixed Application Target

PR #11 merge commit:

`798f48acb461298a34c06ed8ad926327e22e7121`

PR #11 reviewed head contained by that merge:

`7c67ca1c850f2bb789e066f7449c0c259153c20a`

The deployment target for application code is fixed to the PR #11 merge commit above.

The governance commit containing this deployment mission may advance `athena-integration`; do not let that change the fixed application target unless the only descendant changes are documentation/governance and you explicitly record that distinction. Prefer deploying the exact PR #11 merge commit.

Do not silently drift to later application code.

---

## Mission Goal

Deploy DSA Daily Overview v1 to the canonical M5 DSA runtime and prove that the real running application at:

`http://127.0.0.1:8080/`

now exposes the user-facing daily operating picture built in PR #11.

The deployment is complete only when the running process is proven to correspond to the fixed target and the real UI/API behavior is verified against live local DSA + Athena simulation facts.

---

## Canonical M5 Runtime

Canonical DSA repository:

`/Users/m5air/Workbuddy/Li'ang/daily_stock_analysis`

Launchd service:

`com.dsa.webui`

Expected runtime command:

`main.py --webui-only`

Expected bind:

`127.0.0.1:8080`

Athena remains execution infrastructure and must not be modified by this mission.

---

# Phase 0 — Establish Truth Before Mutation

1. Inspect current M5 worktree, branch, HEAD, dirty state, and launchd process.
2. Record the currently deployed SHA before changing anything.
3. `git fetch origin`.
4. Prove that commit `798f48acb461298a34c06ed8ad926327e22e7121` exists locally and contains reviewed head `7c67ca1c850f2bb789e066f7449c0c259153c20a`.
5. Confirm PR #11 is merged in GitHub / remote history.
6. Do not use destructive `reset --hard`, `clean -fd`, or delete user data to make the deployment convenient.
7. If the canonical worktree contains unrelated local changes, preserve them and use a safe reversible deployment method/worktree rather than overwriting them.

Record rollback information before deployment.

---

# Phase 1 — Build and Deploy Fixed Target

Deploy the fixed target safely to the canonical M5 runtime.

At minimum:

1. Ensure the application source used for build is exactly the fixed target.
2. Install/update dependencies only as required by the repository's existing workflow.
3. Build `apps/dsa-web` production assets using the repository's existing supported build path.
4. Ensure the DSA backend will serve the newly built frontend assets.
5. Restart/reload `com.dsa.webui` using the existing launchd pattern.
6. Verify a single expected DSA web process is serving `127.0.0.1:8080`.
7. Prove the running process/source/build correspond to the fixed deployment target rather than a stale checkout or stale static bundle.

Routine deployment blockers are autonomous: stale process, stale frontend bundle, dependency/build issue, reversible launchd issue, static-path issue, cache issue, local port/process issue, or safe configuration mismatch should be diagnosed, fixed, tested, and continued without asking Owner.

---

# Phase 2 — Real Homepage Acceptance

Use the real running M5 application. Do not rely only on mocked Playwright fixtures.

Open / verify:

`http://127.0.0.1:8080/`

The home surface must default to **今日总览**, not the old research-only workbench.

Verify visibly and/or through real GET APIs that the homepage contains the following sections and semantics.

## A. Header

Expected visible structure:

- `Single Brain · 每日事实`
- `今天，系统做了什么`
- tabs/modes:
  - `今日总览`
  - `研究工作台`

Default must be `今日总览`.

Switching to `研究工作台` must preserve the existing original research workflow/search/history experience.

## B. 账户概览

Must use the real connected authoritative Athena snapshot through DSA ingress.

Verify the UI shows actual available fields such as:

- 账户权益
- 现金合计
- 可用现金
- 冻结现金
- 已实现盈亏
- 未实现盈亏
- snapshot currency
- 快照时间
- 核对状态
- 数据质量
- 持仓数量

Do not hard-code expected monetary values.

Expected current connected-account shape from the previous accepted deployment evidence is approximately 14 authoritative positions, but treat the live authoritative Snapshot as source of truth because portfolio facts may naturally change.

If the live snapshot currently has 14 positions, the homepage must visibly report `共 14 项持仓` / equivalent count.

If it has a different legitimate count, record the authoritative count and explain the change; do not force it to 14.

## C. 当前持仓

The homepage must show real connected holdings directly without needing an account-selector trick.

For displayed holdings verify:

- exact `(market, symbol)` identity
- quantity
- available quantity where shown
- latest price
- market value
- unrealized PnL
- currency from authoritative snapshot

`查看全部持仓` must deep-link to:

`/portfolio?account=connected`

Opening `/portfolio` without an account parameter should default to the connected account whenever the connected authoritative snapshot is available.

Connected and manual accounts must remain unaggregated.

## D. 自动投资状态

Using real readiness data, verify the healthy M3 simulation state is represented correctly.

Expected healthy semantics:

- 自动投资：`运行中`
- 当前模式：`模拟交易`
- most recent cycle/result visible
- next expected run visible when available
- pending reconciliation count visible
- latest authoritative snapshot time visible
- `模拟执行授权：开启`

Contract truth for healthy M3:

- `execution_mode=SIMULATION_EXECUTION`
- `execution_authorization=ON`
- scheduler mode `M3_SIMULATION_EXECUTION_ONLY`
- scheduler authority count = 1
- cadence = 3600 seconds

`execution_authorization=ON` here means existing simulation execution authority only; it does not mean LIVE.

## E. 需要关注

If no real warning exists, expected normal UI:

`目前没有需要处理的事项`

If there is a real current warning, display the actual warning and verify it is supported by real facts.

Do not suppress real warnings merely to satisfy the happy-path screenshot.

## F. 今日投资决策

Verify it reads only `SIMULATION_EXECUTION` Decision Scorecards and does not mix M2 Shadow rows.

For current-day decisions, verify factual presentation of:

- BUY / ADD / HOLD
- current quantity
- target quantity
- delta quantity
- rationale
- mandate/requested quantity where factual
- broker submitted quantity where factual
- execution state/reason

Semantics:

- HOLD = neutral
- BLOCKED = warning and distinct from HOLD
- UNKNOWN = `状态待确认` / warning
- ACCEPTED / ACTIVE / PARTIALLY_FILLED = info
- FILLED = success
- BROKER_REJECTED = danger

For a market-closed natural ADD/BUY, expected factual chain may be:

`requested > 0`, `submitted=0`, `filled=0`, reason market closed.

Do not create a trade to manufacture evidence.

## G. 今日研究

Verify current-day research visibility using existing DSA research/history/task/watchlist facts.

At minimum inspect:

- 已完成分析
- 正在分析
- 观察列表覆盖 when available
- 最近市场复盘 when available
- recent research entries / views

Research UI must remain clearly labeled as research/研究观点, not authoritative InvestmentDecision.

If external LLM quota/provider failure currently prevents new research, preserve fail-closed behavior. Do not bypass quota, fabricate research, or force decisions.

## H. 今日动态

Verify timeline is populated only from factual timestamps/statuses currently available.

Do not require every illustrative event type to appear naturally in this deployment window.

Confirm at least that factual current events are rendered with correct semantics and there is no invented chronology.

---

# Phase 3 — Real API Smoke

Perform GET-only smoke against the running DSA service as applicable:

- `/`
- `/portfolio`
- `/portfolio?account=connected`
- `/investment-decisions`
- `/api/v1/portfolio/connected-snapshot`
- `/api/v1/decision-scorecards?mode=SIMULATION_EXECUTION`
- `/api/v1/single-brain/m2/readiness`
- health/readiness endpoint(s) already used by the repository

Verify each major homepage source fails independently if intentionally probed through existing safe test mechanisms; do not break production state to manufacture failure cases.

---

# Phase 4 — Safety / Authority Audit

After deployment reconfirm:

- `LIVE_TRADING=false`
- Athena remains simulation-only
- no SELL / REDUCE capability added
- no RiskPolicy changes
- no canonical contract changes
- no Athena source changes
- no browser-direct Athena access
- no connected Snapshot written into manual ledger
- no connected/manual aggregation
- no new execution/retry/cancel/reconcile control on dashboard
- scheduler authority count = 1
- scheduler cadence remains 3600 seconds
- P1A/P1B remain OFF
- no duplicate scheduler authority was introduced by restart

Do not alter cadence to accelerate verification.

Do not force BUY/ADD/HOLD.

---

# Phase 5 — Tests After Deployment

Run a deployment-appropriate regression set against the fixed target / running environment.

At minimum:

- DailyOverview focused frontend tests
- HomePage focused tests
- PortfolioPage connected-account focused tests
- investment-decisions focused tests
- frontend build
- frontend lint
- real Playwright GET-only smoke for desktop homepage
- real Playwright / browser smoke at ~390px mobile width if feasible without state mutation
- relevant connected portfolio / scorecard / readiness backend focused tests
- `git diff --check`

Do not require a full overnight soak for this deployment.

A short post-restart observation sufficient to confirm launchd/runtime/scheduler did not duplicate is enough.

---

# Phase 6 — Evidence and Closeout

Post a sanitized deployment closeout comment to merged PR #11.

Include:

- fixed target SHA
- M5 deployed/running SHA proof
- M5 worktree/source path used
- launchd service/process evidence
- `127.0.0.1:8080` health
- homepage default `今日总览` evidence
- real connected portfolio count/currency/reconciliation/data-quality evidence
- real holdings visible evidence
- `/portfolio?account=connected` evidence
- research visibility evidence
- investment-decision visibility evidence
- readiness/scheduler/cadence evidence
- LIVE/simulation safety evidence
- test results
- any genuine runtime warnings or limitations
- rollback ref/backups retained

If possible include sanitized screenshots of the real M5 UI. Do not expose sensitive account identifiers, credentials, tokens, or broker secrets.

Deployment closeout must explicitly state:

`DEPLOYMENT PASS`

only if all core deployment acceptance criteria are met.

If deployment succeeds but one non-blocking visual/observability limitation remains, report `DEPLOYMENT PASS WITH LIMITATION` and describe it precisely.

---

# Autonomous Blocker Policy

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Autonomously resolve routine deployment blockers such as:

- stale build/static assets
- stale process
- launchd restart/reload issue
- safe dependency issue
- reversible local config issue
- source/build path mismatch
- port conflict from stale DSA process
- browser cache/static cache
- GET-only smoke tooling issue
- test fixture or test-runner issue that does not require product semantics changes

Continue until deployment acceptance is complete.

## Source-Code Fix Gate

If actual source-code changes are required to make the merged feature work in the real M5 environment:

1. Do not patch `athena-integration` directly.
2. Create a new branch/worktree.
3. Make the minimum source fix.
4. Run focused/full tests appropriate to scope.
5. Push a Draft PR.
6. Report exact HEAD and evidence.
7. Stop at **ARCHITECTURE REVIEW GATE**.

Do not merge that source-fix PR without a new ChatGPT Architecture Review and Owner merge authorization.

---

# OWNER HARD STOP

Stop and ask Owner only if deployment would require any of the following:

- LIVE / real-money trading
- investment-authority change
- sizing/allocation change
- RiskPolicy decision
- SELL / REDUCE enablement
- broker/account permission expansion
- auth/network exposure expansion
- destructive migration or data deletion
- inability to prove what SHA the running process is serving
- scheduler cadence change
- forced trade or forced analysis for acceptance
- irreversible operational change

---

# Forbidden

- Do not enable LIVE.
- Do not force a trade.
- Do not shorten the 3600-second scheduler cadence.
- Do not manually manufacture fills or broker operations.
- Do not blind-retry UNKNOWN execution.
- Do not write Athena Snapshot facts into the manual portfolio ledger.
- Do not aggregate connected and manual portfolio balances.
- Do not modify Athena or RiskPolicy.
- Do not add SELL / REDUCE.
- Do not merge any new source PR.
- Do not expand scope into M4.

---

# Acceptance

Deployment is accepted when a user opening:

`http://127.0.0.1:8080/`

can visibly use the new **今日总览** and answer from real runtime facts:

1. What is the connected account state?
2. What positions are currently held?
3. What research happened today?
4. What investment decisions happened today?
5. Was anything actually submitted, and if not, why?
6. When did the latest automatic-investment cycle run?
7. When is the next cycle expected?
8. Is the system healthy?
9. Is anything requiring attention?

while all existing M3 simulation safety/authority boundaries remain unchanged.
