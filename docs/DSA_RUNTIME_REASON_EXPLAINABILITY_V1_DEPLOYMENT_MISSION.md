# DSA Runtime Reason Explainability v1 — M5 Deployment Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a deployment-alignment and real-runtime acceptance mission. It must verify the new readiness/observability semantics against the existing M3 simulation runtime without changing architecture, permissions, cadence, or investment authority.

---

## Mission Name

**部署 DSA 运行原因可解释性 v1 到 M5，并用真实 Single Brain 运行事实验收**

## Canonical Source

Repository: `soccomp/daily_stock_analysis`

Branch at mission creation: `athena-integration`

Canonical branch head at mission creation:

`2ded7a711098667c3fd462d86d1f52b632a4923d`

This is the merge commit for PR #12 and is the **fixed application deployment target**.

The documentation commit that adds this deployment mission may advance `athena-integration`; do not accidentally deploy that later documentation-only commit as though it were application code. The deployed application source must contain exactly the PR #12 merge content, pinned to `2ded7a711098667c3fd462d86d1f52b632a4923d`, unless a source-fix Draft PR is required under the blocker rules below.

---

# Goal

Deploy the merged Runtime Reason Explainability v1 application to the user's M5 DSA runtime and prove, using real read-only runtime facts, that:

1. `http://127.0.0.1:8080/` serves the PR #12 application code.
2. Daily Overview still renders the existing authoritative connected portfolio and Single Brain status correctly.
3. `FAILED_CLOSED` is recognized as a first-class warning outcome rather than generic `状态待确认`.
4. Scheduler health is presented separately from the latest-cycle outcome.
5. The user-safe failure reason is evidence-backed and conservative.
6. The UI does not claim another scheduled run unless the scheduler facts actually prove one.
7. The latest-cycle proof shows only recorded facts for research / decision / mandate / broker submission.
8. No trading authority, execution permission, scheduler cadence, RiskPolicy, PortfolioSnapshot semantics, Athena behavior, auth exposure, or LIVE state changes.

This is a deployment/acceptance mission, not a feature-development mission.

---

# Existing Runtime Constraints to Preserve

Preserve the already-approved runtime posture:

- DSA main runtime on M5 via launchd `com.dsa.webui`
- official local address `http://127.0.0.1:8080`
- process form `main.py --webui-only`
- loopback-only web binding
- Single Brain scheduler authority exactly one when healthy
- scheduler mode `M3_SIMULATION_EXECUTION_ONLY`
- cadence remains 3600 seconds
- P1A / P1B remain disabled
- DSA execution mode remains `SIMULATION_EXECUTION`
- simulation execution authorization remains the already-approved M3 value
- Athena remains simulation-only; LIVE remains false/disabled
- no SELL / REDUCE capability expansion
- no manual execute / retry / reconcile / cancel controls
- connected PortfolioSnapshot remains authoritative/read-only and isolated from manual portfolio ledgers

Do not modify these settings merely to make acceptance easier.

---

# Phase 1 — Provenance and Preflight

Before deployment:

1. Fetch latest remote refs.
2. Record:
   - `origin/athena-integration` current SHA
   - fixed application target `2ded7a711098667c3fd462d86d1f52b632a4923d`
   - current deployed M5 DSA SHA, if determinable
   - working-tree status
3. Verify the application target contains PR #12 head `c58962c23e4c2f3d3618bfb19f85d61c1b684d0b`.
4. Verify no unreviewed application-code commit exists between the fixed target and the mission document commit.
5. Record a reversible pre-deployment Git ref and preserve existing private rollback material as appropriate.

If the current M5 application is already at the fixed target, do not perform unnecessary mutation; continue directly to acceptance.

---

# Phase 2 — Deploy Application Target to M5

Deploy the exact fixed application target:

`2ded7a711098667c3fd462d86d1f52b632a4923d`

Use the established DSA deployment procedure already proven on M5.

Routine reversible operations are autonomous, including:

- fetch / checkout / detached-target preparation
- static frontend build if required by the existing deployment architecture
- process restart/reload through the existing launchd mechanism when required
- read-only health checks
- rollback preparation

Do not edit production configuration except where a pre-existing reversible deployment mechanism requires no semantic change.

Do not change `.env` values for Single Brain mode, scheduler cadence, execution authorization, auth exposure, Athena endpoint semantics, or trading permissions.

---

# Phase 3 — Running-SHA and Service Verification

Prove the running application corresponds to the fixed target.

Record sanitized evidence for:

- expected application target SHA
- local deployed source SHA
- process / launchd state
- `127.0.0.1:8080` HTTP health
- UI bundle/static assets updated as expected

The canonical acceptance target is the application merge commit, not the later mission-document commit.

---

# Phase 4 — Real M5 Read-Only Acceptance

Use GET/read-only checks only. Do not trigger an analysis or trade merely for evidence.

## A. Daily Overview baseline

Open `/` and verify the default surface remains `今日总览` and still renders:

- 账户概览
- 自动投资状态
- 需要关注
- 当前持仓
- 今日投资决策
- 今日研究
- 今日动态

Confirm the original research workbench remains available.

## B. Connected authoritative account

Verify real DSA ingress still consumes Athena authoritative PortfolioSnapshot without fallback/synthetic data.

Record sanitized facts such as:

- source/authority/read-only/simulation-only truth
- currency
- reconciliation status
- data quality
- position count
- active-order count
- content-hash validation if available

Do not publish balances, holding identities, account identifiers, credentials, cookies, or other private account payloads.

Confirm `/portfolio?account=connected` remains read-only and no manual/trading mutation controls appear for the connected account.

## C. Runtime explainability acceptance

Inspect the real Single Brain readiness response and the rendered home page.

If the latest real cycle is `FAILED_CLOSED`, verify all of the following:

1. The latest result is rendered as `本轮安全停止` or the more specific evidence-backed stage wording, not generic unknown.
2. Scheduler presentation is separate from latest-cycle outcome.
3. If scheduler continuation is actually proven (feature enabled, scheduler enabled, exactly one authority, correct M3 simulation mode/authorization, valid recorded `next_run_at`), the product may show `运行中` and a factual next run.
4. If any of those continuation facts are missing/degraded, the UI must not promise the next cycle; it must show scheduler attention and `下次预计` as unconfirmed or equivalent.
5. Failure reason is sanitized and evidence-backed.
6. A structured/safe known reason may show specific Chinese copy such as `AI 分析额度不足` only if the persisted/runtime evidence proves that category.
7. Unknown/generic historical evidence must remain conservative, such as `研究阶段未完成，具体原因待确认` or generic cycle failure; it must not infer quota/provider/data cause from history/context alone.
8. The proof row for research / investment decision / mandate / broker submission matches recorded facts only.
9. Execution `UNKNOWN` / pending reconciliation remains separate from research fail-closed.
10. Timeline uses warning semantics for fail-closed and real timestamps only.

If the latest real cycle is not `FAILED_CLOSED`, do **not** force one. Instead:

- verify the readiness API contains the additive diagnostics shape without breaking healthy-cycle behavior
- use existing persisted historical fail-closed records if safely available for read-only inspection
- otherwise record that a real current fail-closed rendering could not be re-observed during the deployment window and classify that as an acceptance limitation, not a deployment failure, provided all deterministic tests and real healthy-runtime checks pass

## D. Current-day history preservation

If there are earlier same-day research records or investment decisions, verify they remain visible even if the latest cycle failed closed.

If none exist, do not fabricate them.

## E. Safety posture

Confirm:

- Athena remains simulation-only
- LIVE false/disabled
- one M3 scheduler authority when healthy
- cadence unchanged at 3600 seconds
- P1A/P1B off
- pending execution count factual
- no new execution controls
- no broker/trading mutation was performed for deployment proof

---

# Phase 5 — Regression Verification

Run the smallest responsible post-deployment verification appropriate to this release, including as applicable:

- focused runtime explainability / readiness backend tests
- relevant M2/M3 scheduler and authority tests
- focused Daily Overview frontend tests
- frontend build/lint if deployment architecture requires them
- real GET-only Playwright/smoke on desktop and 390px mobile
- `git diff --check` / clean deployed source confirmation

Do not use test fixes to justify unrelated source changes during this deployment mission.

Known pre-existing test limitations may be disclosed rather than repaired here, including the previously demonstrated order-sensitive intelligence test and yfinance date-boundary tests, provided they still reproduce on the unchanged base and deployment-relevant gates are green.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine deployment blockers are autonomous:

- stale local branch/worktree
- frontend static bundle mismatch
- dependency/build cache issues
- launchd reload/restart needed by normal deployment
- port/process stale state
- reversible path/config discovery
- test invocation/environment issues
- sanitized evidence collection

Diagnose, fix, verify, and continue without asking Owner, as long as the fix does not change product semantics or risk authority.

---

# ARCHITECTURE REVIEW GATE

If real M5 acceptance exposes a source-code defect that requires changing any application source to complete deployment:

1. Do not patch production ad hoc.
2. Create a new branch from the appropriate canonical base.
3. Implement the smallest source fix.
4. Run tests.
5. Push a **Draft PR**.
6. Report exact base/head and evidence.
7. Stop at **Architecture Review Gate**.
8. Do not merge or deploy that source fix without a new authorization cycle.

---

# OWNER HARD STOP

Stop and ask Owner only if completion would require:

- enabling LIVE / real-money trading
- changing investment authority
- changing sizing/allocation logic
- changing RiskPolicy
- enabling SELL / REDUCE
- expanding broker/account permissions
- changing scheduler cadence or authority model
- changing auth/network exposure
- destructive/irreversible migration or data deletion
- forcing analysis/trades solely for acceptance evidence
- altering Athena execution behavior

---

# Phase 6 — Sanitized Deployment Closeout

After completion, post a sanitized deployment closeout to merged **DSA PR #12**.

The closeout must include:

- terminal status: `DEPLOYMENT PASS`, `DEPLOYMENT PASS WITH LIMITATION`, or `DEPLOYMENT BLOCKED`
- fixed application target SHA
- actual running M5 DSA SHA
- process/launchd/HTTP health
- Daily Overview real acceptance result
- authoritative connected-account acceptance result
- real latest-cycle status and explainability result
- scheduler continuation facts and whether next-run wording was justified
- current-day research/decision visibility facts without private holdings/balances
- simulation-only/LIVE/scheduler/cadence/P1A/P1B/pending-execution safety facts
- post-deployment test/smoke evidence
- known non-blocking limitations
- rollback reference/backups
- statement whether any source-fix PR was required

Do not include private balances, holdings identities, broker/account IDs, credentials, tokens, cookies, raw exception dumps, or filesystem secrets.

No overnight soak is required for this UI/observability deployment unless an unexpected runtime defect specifically warrants additional bounded observation.

---

# Acceptance

Deployment is accepted when the M5 runtime is proven aligned to application target `2ded7a711098667c3fd462d86d1f52b632a4923d`, the Daily Overview remains healthy, Runtime Reason Explainability v1 behaves according to real evidence, and the existing Single Brain simulation-only safety posture is unchanged.

**Do not merge anything. Do not change trading authority. Do not deploy an unreviewed source fix.**
