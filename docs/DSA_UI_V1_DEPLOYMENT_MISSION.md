# DSA UI v1 — M5 Deployment Alignment Mission

## MODE

- **Model:** Sol
- **Reasoning:** 高
- **Reason:** 本 Mission 是本地运行态与 GitHub canonical branch 的部署对齐，需要核对 Git SHA、launchd、Web/API/readiness、Single Brain scheduler authority 与回滚安全，但不改变投资权、RiskPolicy、交易能力或产品架构。

---

## 1. MISSION GOAL

把 M5 上 DSA 的**正式运行版本**安全对齐到 GitHub `soccomp/daily_stock_analysis` 的 `athena-integration` 当前 HEAD，并确认刚合并的 UI Architecture v1 / 投资决策可视化 v1 已经真实可用。

本 Mission 是 deployment/alignment，不是功能开发。

成功后必须能证明：

1. GitHub `athena-integration` 被解析并固定为一个 exact target SHA；
2. M5 canonical DSA checkout 与该 target SHA 一致；
3. `com.dsa.webui` 实际运行的代码就是该 target SHA；
4. `/investment-decisions` 新 UI 可访问；
5. read-only decision scorecard list/detail 与 readiness API 可用；
6. 原有 DSA 页面仍可访问；
7. Single Brain M3 运行、安全和 scheduler authority 没有被部署破坏；
8. 没有扩大交易权限、没有改变 cadence、没有触发人为交易。

PR #9 的已批准产品 merge commit 是：

`5ca1ee07b1b735598c68cc60aff7be2204621c71`

由于本 Deployment Mission 文档本身也提交在 `athena-integration`，执行时**不要硬编码上面的 merge SHA 作为最终部署 SHA**。开始执行时先 `git fetch origin`，读取并固定当前：

`origin/athena-integration`

为 `TARGET_SHA`。

要求 `TARGET_SHA` 必须是上述已批准 merge commit 的后代，并包含本 Mission 文档；随后整次部署都使用这个 exact `TARGET_SHA`，不要在执行过程中漂移到更新的远端 HEAD。

---

## 2. CANONICAL LOCATIONS

Repository:

`soccomp/daily_stock_analysis`

Canonical local repo:

`/Users/m5air/Workbuddy/Li'ang/daily_stock_analysis`

Target branch:

`athena-integration`

Launchd service:

`com.dsa.webui`

Expected Web binding:

`127.0.0.1:8080`

Expected launch mode:

`main.py --webui-only`

---

## 3. DEPLOYMENT CONSTITUTION

继续遵守：

> Single Brain, Single Decision, Single Scorecard.

Deployment 只能改变“运行的是哪一个已批准 commit”，不能改变投资语义。

禁止借部署机会修改：

- InvestmentDecision semantics
- Research authority
- RiskPolicy
- sizing
- ExecutionMandate semantics
- ExecutionResult semantics
- PortfolioSnapshot authority
- scheduler cadence
- broker permissions
- auth/network exposure
- live-trading permissions

---

## 4. REQUIRED PRE-FLIGHT

在修改运行态前记录：

- `TARGET_SHA`
- local canonical repo current HEAD
- current branch
- `git status --short`
- `git rev-parse origin/athena-integration`
- launchd service state / PID
- current process command line
- current loopback listener on port 8080
- current Single Brain readiness
- current execution mode / authorization
- current scheduler enabled state / mode / authority count / interval
- current latest authoritative snapshot timestamp
- current pending execution / reconciliation count

如果 canonical repo 存在未知的用户本地修改：

- 不得丢弃；
- 不得 `git reset --hard` 覆盖；
- 使用可逆、安全办法处理；
- 如果无法在不破坏用户修改的前提下完成部署，进入 OWNER HARD STOP 并精确报告。

普通已知构建产物、缓存、日志不属于 Owner Hard Stop，可自主清理。

---

## 5. SYNC / DEPLOY

目标不是“看起来差不多”，而是：

`M5 deployed HEAD == TARGET_SHA`

Codex 自主完成必要的安全步骤，例如：

- fetch
- fast-forward / checkout approved target
- dependency/build refresh（仅必要时）
- frontend production build（如果当前 DSA runtime 需要）
- launchd service restart/reload
- local loopback smoke test

不要创建新的产品 feature branch。

不要修改源代码来“顺便优化”。

如果部署暴露 routine packaging/build/runtime blocker：

**AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE**

但如果修复需要修改 tracked source code：

- 不要直接把修复塞进 `athena-integration`；
- 建立独立 fix branch / Draft PR；
- 运行测试；
- 进入 Architecture Review Gate；
- 在修复被批准前，不宣称部署完成。

---

## 6. RUNTIME SAFETY BASELINE

部署前后必须保持：

- `LIVE_TRADING=false`
- simulation-only baseline
- M3 execution mode不被改成 LIVE
- no SELL / REDUCE automation
- no automated exits
- no RiskPolicy mutation
- no broker permission expansion
- no auth/network exposure expansion

当前本地-only passwordless policy 是既有部署选择：

`ADMIN_AUTH_ENABLED=false`

本 Mission 不得改变它，也不得把服务暴露到非 loopback 地址。

---

## 7. SINGLE BRAIN SCHEDULER ACCEPTANCE

部署后确认：

- exactly one active Single Brain M3 scheduler authority；
- mode 仍为 `M3_SIMULATION_EXECUTION_ONLY`（或当前 canonical 等价名称）；
- interval 仍为 3600s；
- P1A/P1B legacy authorities 仍关闭；
- 没有因为 restart 创建 duplicate scheduler；
- 没有缩短 cadence；
- 没有为了验收强制运行 BUY/ADD；
- restart/reload 后逻辑 cycle 仍遵守已有 dedupe/recovery 语义。

如果自然 cycle 在部署窗口恰好发生：

只观察并记录，不改变 cadence，不伪造 action，不人为促进 broker mutation。

---

## 8. UI / API SMOKE ACCEPTANCE

部署后至少验证：

### Existing DSA

- `/` 可访问
- `/chat` route 可解析
- `/portfolio` route 可解析
- `/decision-signals` 仍可访问，中文显示“研究建议”

### New UI

- `/investment-decisions` 可访问
- Sidebar 有“投资决策”
- 页面可以读取 runtime status + decision timeline
- 有 persisted decision 时可打开“决策档案”
- `?decision=<decision_id>` deep link 可恢复（如当前数据库有可用 decision_id）

### Read-only APIs

至少验证：

- `GET /api/v1/decision-scorecards`
- `GET /api/v1/decision-scorecards/{decision_id}`（如有 persisted item）
- `GET /api/v1/single-brain/m2/readiness`

新页面/新 API 的 smoke traffic 必须保持 GET-only。

不得为了 smoke test 调用任何交易 mutation endpoint。

---

## 9. DATA SEMANTICS ACCEPTANCE

用实际 persisted 数据（如果存在）确认 UI 不破坏以下语义：

- HOLD = 正常决策，“本轮无需交易”；
- BLOCKED = 执行层阻止，不等于 Brain 决策失败；
- UNKNOWN = 状态待确认 / 待核对，不等于失败；
- requested / submitted / filled / remaining quantity 分开；
- 决策前/后账户只来自 persisted authoritative Snapshot A/B；
- 没有 synthetic Snapshot B；
- `(market, symbol)` 仍用于精确持仓身份；
- monetary values 使用 Snapshot 自带 currency；
- Research confidence 与 InvestmentDecision confidence 仍分开。

若生产 persisted 数据没有覆盖某个状态，不要制造 broker mutation。依赖已经通过 PR #9 的 fixture/test evidence 即可。

---

## 10. REGRESSION / SMOKE TESTS

本 Deployment Mission 不要求无意义地重复所有开发阶段测试，但至少：

1. 确认部署 target 是已经通过 PR #9 完整 regression 的 approved lineage；
2. 运行部署后最相关的 focused smoke / health checks；
3. 如果部署步骤重新构建前端，确认 production build 成功；
4. 如果本地 runtime/environment 变化触发异常，运行相应 focused tests；
5. 不得以“服务能启动”替代数据语义验证。

如果因任何代码修复产生新 commit，则必须重新运行与改动相称的完整 regression，并通过 Draft PR 审查。

---

## 11. AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

以下 routine blocker Codex 自主处理：

- git fetch / safe fast-forward
- stale build artifact
- node/python dependency refresh
- frontend rebuild
- launchd restart/reload
- stale local process
- port owner diagnosis
- log inspection
- reversible local config/cache cleanup
- local read-only API smoke failures caused by deployment mechanics

不要把 Owner 变成命令中继。

---

## 12. ARCHITECTURE REVIEW GATE

如果发现必须：

- 修改 tracked product code；
- 修改 DSA/Athena contract；
- 修改 scheduler semantics；
- 修改 Portfolio authority；
- 修改 execution/auth/network semantics；
- 修改 trading permissions；

则创建独立 fix branch / Draft PR，并停止在 Architecture Review Gate。

---

## 13. OWNER HARD STOP

以下立即停止：

- 真实资金 / LIVE trading
- live permission expansion
- SELL / REDUCE capability
- RiskPolicy product change
- investment authority change
- broker permission expansion
- auth/network exposure expansion
- destructive loss of local user changes/data
- irreversible migration

---

## 14. GITHUB CLOSEOUT

部署成功后，不要创建 docs-only closeout commit，以免再次让 GitHub HEAD 与 M5 deployed HEAD 无意义漂移。

请在 **PR #9** 的 Conversation 中追加一条 deployment closeout comment，作为 canonical operational evidence。

Comment 必须包含：

- `TARGET_SHA`
- M5 canonical local HEAD
- `M5 HEAD == TARGET_SHA: YES/NO`
- launchd service status + PID
- bound address/port
- launch command/mode
- frontend build result（如适用）
- UI smoke result
- API smoke result
- scheduler mode / authority count / interval
- execution mode / authorization
- LIVE_TRADING state
- ADMIN_AUTH_ENABLED state
- pending reconciliation count
- broker mutation observed during deployment: YES/NO
- source code changed during deployment: YES/NO
- exact commands/tests used for smoke verification
- known limitations

不要 merge 新东西；本 Mission 的完成事实放在 PR #9 comment 即可。

---

## 15. PASS CONDITION

只有同时满足以下条件才 PASS：

- exact `TARGET_SHA` pinned before deployment；
- target descends from approved PR #9 merge commit；
- M5 canonical repo deployed HEAD equals `TARGET_SHA`；
- service 正常运行于 loopback；
- 新“投资决策” UI 可访问；
- 原 DSA 核心页面未损坏；
- read-only scorecard/readiness API 正常；
- exactly one M3 scheduler authority；
- cadence 未改变；
- simulation-only / LIVE false；
- no SELL/REDUCE；
- no auth/network expansion；
- no broker mutation was manufactured for acceptance；
- PR #9 已留下完整 deployment closeout comment。

完成后报告：

`MISSION STATUS: PASS`

以及 exact `TARGET_SHA`。
