# DSA 持仓统一账户中心 v1 — Mission

## MODE

- **Model:** Sol
- **Reasoning:** 高
- **Reason:** 本 Mission 需要在不破坏现有 DSA 持仓/手工账本能力的前提下，把 Athena authoritative PortfolioSnapshot 作为“已连接账户”只读事实自然接入同一个持仓页面，并补齐只读 API、前端状态语义、响应式交互与回归测试；复杂度跨 UI / API / Single Brain 事实边界，但不改变投资权、RiskPolicy、执行权或交易权限。

---

## 1. MISSION GOAL

把现有 DSA **“持仓”** 页面升级为一个统一的账户与持仓中心，同时保留原版 DSA 的视觉语言、交互习惯和全部手工账户能力。

最终用户应自然理解：

> **“持仓”就是我所有账户和持仓的统一入口。手工账户仍然可以自己维护；已连接账户来自真实的 Athena / broker 账户事实，只读展示，自动投资使用的是这份权威事实。**

本 Mission 只实现 **v1 read-only connected account integration**，不是交易控制台，也不是 Portfolio Truth 的新副本。

成功后必须满足：

1. `/portfolio` 仍然是唯一顶层“持仓”入口；
2. 现有 DSA 手工账户、手工交易、现金流水、CSV 导入、公司行动、成本法、风险分析等原功能完整保留；
3. 同一页面中新增明确区分的 **“已连接账户”**；
4. 已连接账户展示 Athena authoritative `PortfolioSnapshot` 的真实事实；
5. 已连接账户在 DSA 中严格只读，不出现任何本地手工修改、导入、下单、重试、撤单或核对操作；
6. DSA 不把 Athena Snapshot 写入现有手工 portfolio ledger，不创建伪装成手工账户的镜像记录；
7. Single Brain 仍只使用 authoritative Athena PortfolioSnapshot 作为账户事实；
8. 不改变 Brain、RiskPolicy、ExecutionMandate、ExecutionResult、scheduler、Athena、LIVE、SELL/REDUCE 或任何交易权限；
9. UI 继续让用户感觉“还是原来的 DSA，只是持仓现在认识已连接账户了”。

---

## 2. CANONICAL PRODUCT / AUTHORITY RULES

以下规则不可弱化。

### 2.1 One product

用户面对的产品只有 **DSA**。

- 不新增 Athena 顶层页面；
- 不新增“Portfolio Truth / 账户实况 / Operations”顶层导航；
- Athena 只作为 DSA 中已连接账户的事实来源与执行基础设施出现。

### 2.2 Two account sources, one account center

“持仓”统一展示两类账户，但两类账户的事实所有权必须清晰隔离：

#### A. 手工账户

来源：现有 DSA portfolio ledger。

必须保留现有能力，包括但不限于：

- 创建 / 选择 / 删除或停用现有手工账户；
- 手工交易录入；
- 现金流水；
- CSV broker import；
- corporate actions / dividend / split 等现有能力；
- FIFO / AVG 等现有成本法；
- 组合快照、风险分析、FX / data quality、AI risk signals 等原功能。

这些功能继续遵循原 DSA 语义。

#### B. 已连接账户

来源：Athena authoritative `PortfolioSnapshot`。

必须：

- `source = ATHENA_RUNTIME`；
- `authoritative = true`；
- `read_only = true`；
- 当前部署继续要求 `simulation_only = true`；
- UI 明确显示“已连接账户”“只读”“模拟账户”等真实状态；
- 所有资金、持仓、订单、PnL、快照时间、核对状态、数据质量均来自 canonical Snapshot；
- 不在 DSA 本地手工 portfolio ledger 中 materialize / mirror / upsert 一份账户副本。

### 2.3 No authority blending

禁止：

- 用手工账户数据补 Athena Snapshot 缺失字段；
- 用 Athena Snapshot 覆盖手工账户 ledger；
- 把两类账户余额/持仓静默合并成一个“总资产”；
- 为了 UI 好看自行推导 broker 未提供的事实；
- 从 fill / order 推算 synthetic PortfolioSnapshot；
- 把 DSA 手工账户标成 Single Brain authoritative truth。

如果事实来源不同，UI 必须能让用户看出来源不同。

---

## 3. AUDIT FIRST — DO NOT REWRITE PORTFOLIO BLINDLY

开始实现前，Codex 必须先审计 `athena-integration` 当前真实代码，至少包括：

- `apps/dsa-web/src/pages/PortfolioPage.tsx`；
- portfolio 前端 API / types / tests；
- `api/v1/endpoints/portfolio.py` 及 schema；
- `PortfolioService` / repository / storage 相关实现；
- 当前 M2/M3 PortfolioSnapshot ingress / readiness / transport；
- 当前 `PortfolioSnapshot` contract；
- 当前 UI common components 与 portfolio 文案；
- PR #9 后的 `/investment-decisions` 账户展示语义。

先列出：

1. 当前手工账户功能清单；
2. 哪些 UI 控件会产生本地 portfolio mutation；
3. 哪些代码可以原样复用；
4. authoritative Snapshot 当前最短、最安全的 DSA read-only 获取路径；
5. 是否已经存在可直接复用的 full Snapshot GET surface。

**优先复用现有 read-only ingress。不要为了本 Mission 再造第二条 Athena 事实通路。**

---

## 4. TARGET UX — `/portfolio`

保持现有 DSA Shell / Sidebar / PageHeader / Card / Badge / StatusDot / Drawer / 表格 / 响应式语言。

不要改造成 Bloomberg、券商终端或独立量化 dashboard。

### 4.1 Page identity

顶层导航仍叫：

**持仓**

路由仍是：

`/portfolio`

不新增平行顶层“账户实况”。

### 4.2 Account source selection

在不破坏现有账户选择器的前提下，把账户来源做成清晰、自然的分组/分段：

- **已连接账户**
- **手工账户**

具体控件形态应优先延续现有 DSA 账户选择器，而不是重做整页导航。

要求：

- 用户能一眼看出当前选中账户是哪种来源；
- 已连接账户不需要、也不得在手工账户表中创建 fake account row；
- 如果已连接账户暂时不可用，手工账户功能仍正常可用；
- 不要把“连接失败”误报成“账户为空”。

### 4.3 Connected account header

选中已连接账户时，顶部应使用真实事实展示例如：

- 已连接账户
- 模拟账户（仅在 canonical fact 支持时）
- 只读
- broker / account mode（用正常用户语言）
- 快照时间
- 核对状态
- 数据质量

技术性的 `account_id`、snapshot hash、revision、producer 等默认隐藏在“技术详情”。

### 4.4 Connected account summary

使用 authoritative Snapshot 显示：

- 账户权益
- 现金
- 可用资金
- 冻结 / 保留资金
- 已实现盈亏
- 未实现盈亏
- 币种
- 快照时间

**货币必须使用 Snapshot 自带 `currency`，不得硬编码 CNY。**

### 4.5 Connected positions

只读持仓表至少展示 canonical facts 中实际存在的：

- 市场
- 股票代码
- 数量
- 可用数量
- 平均成本
- 最新价格
- 市值
- 未实现盈亏
- price time / source（如果适合当前 UI 密度，可放详情/次级信息）

instrument identity 必须按 canonical **`(market, symbol)`** 处理，禁止 symbol-only 混淆。

允许提供纯导航动作，例如：

- 查看股票分析
- 查看研究建议
- 查看投资决策

但只有在现有目标页面支持确定性参数时才加；不得用模糊 symbol 匹配伪造 lineage。

### 4.6 Active orders

若 authoritative Snapshot 有 active orders，应以**只读**方式展示必要事实：

- 方向
- 数量
- 已成交 / 剩余
- 状态
- 限价
- 提交时间

禁止新增：

- 撤单
- 重试
- 重新提交
- 修改订单
- “立即执行”

### 4.7 Limitations / reconciliation

如果 Snapshot 是：

- `PENDING_RECONCILIATION`
- `DEGRADED`
- `UNKNOWN`
- data quality 低
- limitations 非空

必须在用户可见层明确表达。

**UNKNOWN 不是失败，也不是成功。**

不得隐藏风险状态后仍显示“账户正常”。

### 4.8 Manual account behavior

选中手工账户时：

- 当前所有原功能仍按原逻辑工作；
- 原来的 mutation controls 仍只针对手工账户；
- 不因为新增 connected account 而大规模重排/删除旧功能；
- 原有测试与用户习惯优先保留。

---

## 5. BACKEND — READ-ONLY CONNECTED SNAPSHOT PROJECTION

先审计现有 API。如果已经存在可安全复用、能返回 full canonical PortfolioSnapshot 的 DSA GET endpoint，则优先复用。

如果没有，允许在 DSA 新增一个最小 read-only endpoint，建议语义：

`GET /api/v1/portfolio/connected-snapshot`

最终 path 可根据当前 router 结构做最小一致化调整，但 PR 报告必须说明选择。

要求：

1. GET-only；
2. 复用现有 M2/M3 Athena runtime snapshot ingress / canonical parser；
3. 返回 canonical authoritative Snapshot 或一个不改变语义的只读 projection；
4. canonical hash / contract validation 必须保留；
5. 不写入 DSA manual portfolio tables；
6. 不触发 broker mutation；
7. 不调用 Athena POST / execution / reconcile / cancel surface；
8. 不创建 `ExecutionMandate`；
9. 不改变 readiness / scheduler / M3 execution state；
10. auth 行为沿用现有 DSA portfolio/readiness 的既有策略，不扩大网络或信任边界。

### Fail closed

如果 authoritative Snapshot：

- 不可获取；
- contract invalid；
- source/authority/read-only/simulation safety 不满足；
- 过期/未来时间超出现有 accepted 语义；

connected account surface 必须明确 unavailable / degraded，而不是：

- fallback 到手工账户数据；
- 返回伪造空账户；
- 使用缓存值但不标记状态；
- 自行修正 canonical timestamps / hashes。

---

## 6. FRONTEND DATA MODEL

前端可以建立纯 UI view model，例如：

- `source: "CONNECTED" | "MANUAL"`
- `readOnly: boolean`

但这只是 presentation metadata，不得改变后端事实所有权。

connected account 的核心资金/持仓/订单字段必须直接来自 Snapshot projection。

不要把两种账户硬塞进同一个可变 backend schema；除非经过 Architecture Review Gate 证明不会污染 authority semantics。

---

## 7. CHINESE-FIRST PRODUCT LANGUAGE

主要用户层不要出现一屏内部 contract 名称。

建议用户语言：

- Connected Account → 已连接账户
- Manual Account → 手工账户
- PortfolioSnapshot → 账户快照
- Authoritative → 权威账户事实（仅在需要解释时）
- Read-only → 只读
- Simulation → 模拟账户 / 模拟交易账户（按实际 fact）
- Reconciled → 已核对
- Pending Reconciliation → 待核对
- Degraded → 核对受限
- Unknown → 状态待确认
- Data Quality → 数据质量
- Active Orders → 当前挂单

`PortfolioSnapshot`、`snapshot_id`、`broker_snapshot_ref` 等仅允许出现在折叠技术详情。

---

## 8. CROSS-PAGE RELATIONSHIPS

持仓是“我现在有什么”的入口。

建议关系：

- 持仓 → 股票分析
- 持仓 → 研究建议
- 持仓 → 投资决策
- 投资决策 → 持仓

但：

- position → research 可以按明确 `(market, symbol)` 导航；
- research → specific InvestmentDecision 必须有 deterministic `decision_id` / `source_report_id` lineage；
- 不允许“同股票所以大概是这条决策”的 fuzzy link。

---

## 9. OUT OF SCOPE / FORBIDDEN

本 Mission 不做：

- Athena repo 代码修改；
- 新 Athena UI；
- LIVE trading；
- broker/account permission 扩大；
- SELL / REDUCE / automated exits；
- RiskPolicy editor；
- Brain sizing / allocation 变化；
- ExecutionMandate / ExecutionResult contract 变化；
- scheduler cadence / authority 变化；
- auth / network exposure 变化；
- connected account 下单 / 撤单 / 重试 / reconcile 按钮；
- 手工账户到 Athena 的“同步”；
- Athena Snapshot 到 DSA manual ledger 的复制；
- 两类账户净值自动聚合；
- major Home redesign；
- 全站视觉重做。

---

## 10. AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

以下均为 Codex 自主处理，不要把 Owner 当消息中转：

- worktree / branch / dependency / TypeScript / API client；
- route / schema / read-only service；
- current PortfolioPage 拆组件；
- 测试 fixture / mock；
- CSS / responsive；
- dev server / build；
- GET endpoint 命名在现有 router 中的最小一致化；
- local-only read smoke；
- ordinary test failures / lint / build blockers；
- reversible debug/config used only for test evidence。

建议 branch：

`ui/portfolio-account-center-v1`

Base：

`athena-integration`

使用独立 worktree，不在 canonical deployment worktree 直接开发。

---

## 11. ARCHITECTURE REVIEW GATE

出现以下情况时，完成最大安全实现/诊断后停在 reviewable boundary：

- 需要修改 Athena repo；
- 需要改变 PortfolioSnapshot contract；
- 需要改变 authoritative portfolio truth 语义；
- 想把 connected Snapshot 写入手工 portfolio DB；
- 想统一两类账户 backend schema 且会影响事实所有权；
- 需要改变 M3 snapshot ingress / freshness / hash semantics；
- 需要新增任何 portfolio/trading mutation API；
- 需要改变投资决策或 execution semantics；
- 发现现有手工账户与 connected account 无法在不混淆 authority 的前提下共存。

返回：

`ARCHITECTURE REVIEW GATE: <reason>`

---

## 12. OWNER HARD STOP

仅以下情况找 Owner：

- 实盘 / 真钱；
- live / broker permission 变化；
- SELL / REDUCE / automated exit；
- RiskPolicy 产品选择；
- 投资权 / capital allocation authority 变化；
- auth / credentials / network exposure；
- destructive / irreversible migration；
- 删除或实质性改变原 DSA 用户功能；
- 需要一个真正新的用户级产品决策，且无法由既定 UI architecture 推导。

---

## 13. REQUIRED TESTS

### Backend

至少覆盖：

- connected snapshot endpoint GET-only；
- canonical Snapshot validation；
- source / authoritative / read_only / simulation_only safety；
- exact currency preservation；
- `(market, symbol)` identity preservation；
- active order quantities/status preservation；
- reconciliation/data quality/limitations preservation；
- invalid/unavailable snapshot fail closed；
- no manual portfolio DB writes；
- no execution/mandate/reconcile/cancel calls；
- auth behavior；
- architecture dependency guard。

### Frontend

至少覆盖：

- “已连接账户” / “手工账户” clearly distinct；
- manual account existing controls remain available for manual selection；
- connected selection hides/disables all manual mutation controls；
- connected facts use Snapshot currency；
- same symbol / different market adversarial position fixture；
- reconciliation / degraded / unknown visible semantics；
- no buy/sell/retry/cancel/reconcile/manual-trade control on connected account；
- empty/unavailable connected state does not masquerade as zero-balance account；
- existing Portfolio tests remain green；
- responsive desktop/mobile；
- original routes/navigation unchanged。

### Regression

Run and report exact counts for:

- DSA Python full gate / architecture suite；
- frontend full test suite；
- TypeScript build；
- lint；
- relevant Playwright/E2E if present。

---

## 14. MANUAL / VISUAL ACCEPTANCE

Use sanitized read-only fixtures or actual authoritative simulation snapshot where safe.

Must provide evidence for at least：

1. **已连接账户 — normal reconciled state**；
2. **已连接账户 — degraded / pending / unavailable state**（fixture 可接受，不得制造 broker 异常）；
3. **手工账户 — original mutation workflows still visible**；
4. desktop；
5. mobile。

禁止为了截图制造交易或账户 mutation。

视觉验收：

- 仍明显是原 DSA；
- 不出现第二套设计系统；
- 不出现 giant raw JSON；
- 不把 infrastructure diagnostics 放成主视觉；
- source/read-only/safety 状态足够清楚但不过度工程化。

---

## 15. DOCUMENTATION DELIVERABLE

新增：

`docs/DSA_PORTFOLIO_ACCOUNT_CENTER_V1.md`

记录：

- account source model；
- manual vs connected authority；
- `/portfolio` page responsibilities；
- read-only API boundary；
- failure semantics；
- cross-page navigation；
- deferred future work。

必要时对 `docs/DSA_UI_ARCHITECTURE_V1.md` 做最小 cross-reference 更新，不要重写已有 baseline。

---

## 16. DRAFT PR FINAL REPORT

Draft PR 必须包含：

- Mission Status
- Architecture: PASS / BLOCKED
- UI: PASS / BLOCKED
- Read-only Connected Account API: PASS / BLOCKED
- Existing Manual Portfolio Preserved: YES / NO
- Chinese-first: PASS / BLOCKED
- Responsive: PASS / BLOCKED
- Regression: PASS / BLOCKED
- Trading authority unchanged: YES / NO
- Athena repo changed: YES / NO
- PortfolioSnapshot contract changed: YES / NO
- Manual ledger receives Athena data: YES / NO
- Live trading changed: YES / NO
- SELL/REDUCE introduced: YES / NO
- Scheduler changed: YES / NO
- Exact HEAD SHA
- Exact test counts
- Visual evidence paths
- Known limitations
- Architecture review requested: YES

Mission 允许 Codex：

- 开发 / 测试 / debug；
- branch / worktree commits；
- push；
- Draft PR；
- sanitized review evidence。

**不授权 merge。**

**不授权 production deploy。**

达到 merge-ready 后停在 Architecture Review Gate，等待 ChatGPT review。

---

## 17. PASS CRITERIA

本 Mission PASS，当且仅当：

> 用户进入原来的“持仓”，既能继续正常使用全部手工账户功能，也能在同一产品心智中查看一个明确标记为“已连接账户”的 Athena authoritative simulation account；两类账户在 UI 上统一、在事实所有权上严格隔离；connected account 全程只读，所有资金/持仓/订单/状态均来自 canonical Snapshot；没有新增任何交易权、投资权、RiskPolicy、SELL/REDUCE、LIVE、scheduler 或 Athena authority 变化。
