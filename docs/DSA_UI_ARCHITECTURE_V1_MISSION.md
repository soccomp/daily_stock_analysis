# DSA UI Architecture v1 + 投资决策可视化 v1 — Mission

## MODE

- **Model**: Sol
- **Reasoning**: 高
- **Reason**: 本 Mission 涉及 DSA 现有 Web UI、只读 API、Single Brain 持久化数据语义和跨页面产品信息架构，需要较强的跨层理解，但不改变投资决策权、执行权、RiskPolicy 或交易权限，因此不需要“极高”。

---

## 1. MISSION GOAL

在不破坏原版 DSA 功能、视觉体系和交互习惯的前提下：

1. 正式冻结“未来完成版 DSA”的 UI / 信息架构 v1；
2. 新增第一个真正属于 Athena/DSA 整合后的产品能力：**投资决策**；
3. 将当前内部已有的自动投资运行状态、InvestmentDecision、ExecutionResult、PortfolioSnapshot 和 Single Decision Scorecard 转化成普通中文用户可以理解的只读产品界面；
4. 将原有“AI 建议”在用户界面中更名为“研究建议”，明确其属于资产研究观点，而不是账户投资决策；
5. 不改变任何投资、执行、账户、RiskPolicy、调度或权限语义。

最终用户应该感觉：

> 这仍然是原来的 DSA，只是现在自然增加了账户级自动投资决策能力。

---

## 2. REPOSITORY / BASELINE

- Repo: `soccomp/daily_stock_analysis`
- Canonical local repo: `/Users/m5air/Workbuddy/Li'ang/daily_stock_analysis`
- Base branch: `athena-integration`

本 Mission 原则上只修改 DSA。

**不要修改 Athena repo。**

如果发现必须修改 Athena contract/API 才能完成本 Mission：进入 **ARCHITECTURE REVIEW GATE**，不要自行扩大跨 repo scope。

自行建立独立 worktree / branch。建议 branch：

`ui/investment-decisions-v1`

不要直接在 `athena-integration` 工作区做开发性修改。

---

## 3. PRODUCT CONSTITUTION

必须继续遵守：

> Single Brain, Single Decision, Single Scorecard.

- 研究层拥有解释权；
- 决策层拥有资本配置权；
- 执行层拥有操作权但没有投资判断权；
- 研究层判断资产，不判断账户该怎么动；
- DSA 管目标状态；
- Athena 管事实状态；
- UI 只是观察层。

UI 不获得新的投资权、执行权或账户事实解释权。

特别禁止：

- UI 自行计算最终下单数量；
- UI 自行修改 Brain 决策；
- UI 将研究建议解释为账户交易指令；
- UI 根据缺失数据“推测”账户状态；
- UI 合成 Snapshot B；
- UI 将 UNKNOWN 自动解释为失败或成功；
- UI 提供自动重试交易功能。

---

## 4. GLOBAL UI ARCHITECTURE V1

必须创建并提交：

`docs/DSA_UI_ARCHITECTURE_V1.md`

该文档成为后续 DSA UI 改造的 canonical UI architecture baseline。

文档至少冻结以下内容。

### 未来一级导航

- 首页
- 问股
- 选股
- 持仓
- 研究建议
- 投资决策
- 回测
- 告警
- 用量
- 设置

### 架构原则

1. 保留原 DSA Shell、Sidebar、Card、Drawer、PageHeader、Badge、主题系统和响应式设计语言；
2. 不建立独立 Athena UI；
3. Athena 是底层执行与账户事实基础设施，用户看到的是一个 DSA；
4. “持仓”未来成为唯一账户与持仓中心；
5. “研究建议”回答：“这只股票怎么看？”；
6. “投资决策”回答：“结合当前账户，我到底应该怎么做？”；
7. “首页”仍然以研究工作台为核心，不重构成交易终端；
8. “决策档案”不是一级导航，它是投资决策的详情视图；
9. 中文优先；
10. 内部工程合同名不能直接变成主要 UI 文案。

同时记录未来但本 Mission 不实现的阶段：

- 持仓：已连接账户 + 手工账户统一模型；
- 首页：今日投资动态；
- 研究建议 ↔ 投资决策进一步联动；
- 告警 / 回测与真实投资决策联动。

---

## 5. 中文产品语言规范

主要界面禁止直接显示：

- Single Brain
- Portfolio Truth
- ResearchBundle
- PortfolioSnapshot
- RiskPolicy
- InvestmentDecision
- ExecutionMandate
- ExecutionResult
- Decision Scorecard
- Operations
- PENDING_RECONCILIATION
- BLOCKED
- UNKNOWN
- SIMULATION_EXECUTION

内部代码、API、数据库、debug 详情可以继续使用英文。

主要用户界面采用：

- Single Brain / M3 runtime → **自动投资**
- ResearchBundle → **研究依据**
- PortfolioSnapshot → **账户快照**
- Snapshot A → **决策前账户**
- RiskPolicy → **风险约束**
- InvestmentDecision → **投资决策**
- ExecutionMandate → **执行指令**
- ExecutionResult → **执行结果**
- Snapshot B → **决策后账户**
- Decision Scorecard → **决策档案**
- SIMULATION_EXECUTION → **模拟交易**
- BUY → **买入**
- ADD → **加仓**
- HOLD → **持有**
- FILLED → **已成交**
- PARTIALLY_FILLED → **部分成交**
- ACCEPTED → **已接受**
- ACTIVE → **挂单中**
- BLOCKED → **已阻止**
- BROKER_REJECTED → **券商拒绝**
- EXPIRED → **已过期**
- CANCELLED → **已取消**
- UNKNOWN → **状态待确认**
- PENDING_RECONCILIATION → **待核对**
- RECONCILED → **已核对**
- DEGRADED → **核对受限**
- NOT_REQUIRED → **无需核对**

技术标识如 `decision_id` / `mandate_id` / hash：默认不展示，只允许在“技术详情”折叠区展示。

---

## 6. STATUS / COLOR SEMANTICS

复用 DSA 已有 Badge / StatusDot，不创造新的颜色体系。

重要规则：**颜色表达状态，不表达投资方向。**

- BUY / ADD 不因为是买入而显示 success；
- HOLD 也不是 warning。

建议：

- 投资动作：BUY / ADD → info；HOLD → default；
- 运行正常 / 已成交 / 已核对 → success；
- 已接受 / 挂单中 / 部分成交 → info；
- 已阻止 / 已过期 / 待核对 / UNKNOWN → warning；
- 券商拒绝 / 确认执行失败 → danger；
- 已取消 → default。

UNKNOWN 必须视觉明显，但不得显示为“交易失败”。

---

## 7. IMPLEMENTATION SCOPE — 投资决策

新增一级导航：**投资决策**

建议 route：

`/investment-decisions`

使用现有：

- AppPage
- PageHeader
- Card
- Badge
- StatusDot
- Drawer
- InlineAlert
- EmptyState
- Pagination

不要另建一套视觉组件体系。

### A. Page Header

标题：

**投资决策**

说明：

**查看自动投资的决策、执行情况和账户变化。**

### B. 自动投资状态区

展示真实后端事实，例如：

- 自动投资：运行中 / 未运行 / 需要关注
- 交易模式：模拟交易
- 最近运行
- 下次预计运行
- 待核对事项数量
- 最近账户快照时间

所有信息必须来自 read-only backend facts。

禁止 hardcode：

- “运行正常”
- “实盘关闭”
- “账户已连接”

如果后端没有足够事实支持该文案。

如果 LIVE_TRADING / live trading permission 已存在于 config，可以增加一个纯只读 readiness projection。只能读取现有配置事实。

不得改变配置语义、默认值、权限或授权逻辑。

### C. 决策时间线

默认展示当前 M3 / SIMULATION_EXECUTION 决策。

卡片至少显示：

- 时间
- 股票代码
- 市场
- 投资动作
- 当前数量
- 目标数量
- 变化数量
- 简要决策理由
- 执行状态
- 待核对状态（如有）

BUY / ADD 必须明确展示：

> 当前 X 股 → 目标 Y 股  
> 本次变化 Z 股

HOLD 必须显示：

> 当前 X 股 → 目标 X 股  
> 继续持有，本轮无需交易

禁止显示：

- “HOLD 未执行”
- “HOLD 执行失败”

### D. Quantity semantics

如果存在执行结果，必须分开显示：

- 决策数量
- 请求数量
- 提交数量
- 成交数量
- 剩余数量

不得把 `requested_quantity` / `submitted_quantity` / `filled_quantity` 合并成一个“成交数量”。

必须保留 exact-quantity semantics。

### E. 执行状态

例如：

> 加仓 900 股
>
> 执行结果：已阻止
>
> 原因：市场已休市

而不是：

> 投资决策失败

投资决策本身和执行结果必须视觉分层。

---

## 8. 决策档案 DRAWER

点击“查看决策档案”打开右侧 Drawer。

- 桌面：右侧详情抽屉；
- 手机：允许扩展为近全屏 / 全屏详情，保持现有 Drawer 响应式语言。

详情固定按以下用户顺序组织。

### 1. 研究依据

展示：

- 市场环境
- 行业观点
- 基本面
- 技术面
- 估值
- 情报
- 资金面
- 牛 / 基准 / 熊情景
- 催化因素
- 风险因素
- 研究置信度

不要默认显示 model provider / prompt hash。

### 2. 决策前账户

只能使用 Scorecard 的 authoritative Snapshot A。

展示：

- 账户模式
- 权益
- 现金
- 可用资金
- 相关股票当前数量
- 相关股票成本 / 市值
- 快照时间
- 核对状态

### 3. 风险约束

用普通中文描述 Brain 当时使用的 RiskPolicy。

不得允许修改。

### 4. 投资决策

展示：

- 买入 / 加仓 / 持有
- 当前数量
- 目标数量
- 变化数量
- 目标权重
- 预期收益
- 预期风险
- 置信度
- 决策理由
- 风险理由
- 有效期

### 5. 执行情况

HOLD：

> 本轮无需交易。

BUY / ADD：

展示：

- 执行指令
- 请求数量
- 限价
- 执行结果
- 提交数量
- 成交数量
- 剩余数量
- 成交均价
- 费用
- 券商原因 / 阻止原因
- 核对状态

### 6. 决策后账户

只允许使用 Scorecard Snapshot B。

如果 Snapshot B 不存在：

> 尚无决策后账户快照

不得自行从 Snapshot A + fill 计算 synthetic Snapshot B。

---

## 9. DEEP LINK

决策档案必须支持可恢复 URL，例如：

`/investment-decisions?decision=<decision_id>`

刷新页面后，如果 decision_id 有效，自动打开相同决策档案。

关闭 Drawer：恢复到投资决策列表 URL。

不要把 URL 设计成必须依赖 React 临时 state。

---

## 10. BACKEND — READ-ONLY DECISION LIST API

现有：

`GET /api/v1/decision-scorecards/{decision_id}`

保持兼容，不改变现有 response semantics。

新增只读列表 API：

`GET /api/v1/decision-scorecards`

支持分页。

建议支持：

- `page`
- `page_size`
- `symbol`
- `action`
- `mode`
- `source_report_id`

不要为了 UI 引入新的可变投资表。

列表必须基于现有 immutable `single_decision_scorecards` 读取，按 `created_at DESC`。

列表 summary 至少返回：

- decision_id
- created_at
- source_report_id
- account_id
- symbol
- market
- action
- current_quantity
- target_quantity
- delta_quantity
- confidence
- rationale
- mode
- execution_status
- reconciliation_status
- requested_quantity
- submitted_quantity
- filled_quantity
- remaining_quantity
- average_fill_price
- block_reason
- broker_reason
- snapshot_b_available

如果某字段没有 factual source：返回 null，禁止猜测。

默认投资决策页面只展示 `SIMULATION_EXECUTION`。

历史 M2 Shadow scorecards 不应突然污染当前投资决策时间线。

API 可以支持 mode filter，供以后历史查看使用。

---

## 11. READINESS PROJECTION

继续复用：

`/api/v1/single-brain/m2/readiness`

它虽然历史命名仍然是 m2，本 Mission 不需要重命名 internal API。

可以做最小只读增强，但必须保持向后兼容。

UI 所需事实包括：

- feature enabled
- execution mode
- execution authorization
- scheduler enabled
- authority count
- interval
- next run
- latest authoritative snapshot
- pending execution count
- latest execution state

如果需要显示“实盘交易：关闭”，必须从已有真实配置状态投影。

如果无法可靠确认：不要显示该断言。

绝对禁止 UI 自行从 `simulation_only` 推导整个系统永远没有 live 权限。

---

## 12. “AI 建议” → “研究建议”

用户可见导航：

`AI 建议` → `研究建议`

页面标题和主要说明同步修改。

原 route：

`/decision-signals`

保持不变。

内部代码：

- DecisionSignalsPage
- decisionSignalsApi
- DecisionSignal

等名称本 Mission 不要求重构，避免无意义的大规模 rename。

在研究建议页面明显加入一句普通中文说明：

> 这里展示的是股票研究观点，不代表账户实际交易。

不要删除该页面现有：

- 筛选
- 时间线
- 反馈
- 统计
- 重新评估
- 归档/关闭等原功能

现有功能必须保持。

---

## 13. CROSS-PAGE RELATION

本 Mission 至少在 architecture doc 固化：

- 首页 → 股票分析
- 股票分析 → 研究建议
- 研究建议 → 投资决策
- 投资决策 → 决策档案
- 投资决策 → 持仓
- 持仓 → 股票分析 / 研究建议 / 投资决策

本 Mission 实现范围内：

如果能够通过 `source_report_id` / `decision_id` 无歧义建立“研究建议 → 投资决策”关系，可以加入：

> 查看相关投资决策

如果需要 fuzzy symbol matching 或猜测关系：不要实现。

只允许 deterministic lineage link。

---

## 14. PORTFOLIO / 持仓

本 Mission 不实施“已连接账户 + 手工账户”改造。

但是 architecture doc 必须冻结未来原则。

### 手工账户

继续保留 DSA 当前的：

- 新建账户
- 手工交易
- 现金流水
- CSV
- 分红
- 拆股

等能力。

### 已连接账户

未来以 Athena authoritative PortfolioSnapshot 为事实源。

已连接账户未来不得允许：

- 手工改仓位
- CSV 覆盖券商事实
- 删除券商交易事实
- 通过 DSA 本地账本伪造券商持仓

严禁本 Mission 为了展示账户状态，把 Athena snapshot 写进现有手工 Portfolio ledger。

---

## 15. OUT OF SCOPE

本 Mission 不允许：

- SELL
- REDUCE
- 任何自动卖出/减仓
- LIVE trading
- 实盘授权
- Broker permission 扩张
- 修改 RiskPolicy 产品语义
- 修改 Brain sizing
- 修改 InvestmentDecision 合同语义
- 修改 ExecutionMandate 合同语义
- 修改 ExecutionResult 合同语义
- 修改 Snapshot authority
- 改变 M3 scheduler cadence
- 强制产生 BUY / ADD
- 强制触发交易
- 人工制造 simulation fill
- 交易 retry 按钮
- “强制执行”按钮
- “立即买入”按钮
- “立即卖出”按钮
- RiskPolicy 编辑器
- 账户权限开关
- Athena 管理页面
- Portfolio Truth 独立一级页面
- Operations 独立一级页面
- 大规模重写原 DSA 首页
- 大规模重写原 DSA 视觉系统

---

## 16. AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

本 Mission 授权 Codex 自主处理：

- 依赖问题
- TypeScript 类型问题
- API client 适配
- 测试 fixture
- mock
- 路由冲突
- CSS / responsive bug
- 数据库 read query
- schema 增补
- 分页
- 既有 lint/test failures caused by this work
- worktree/branch
- 开发服务器
- 浏览器测试
- 测试数据构造
- 可逆开发配置

遇到普通 blocker：

> 诊断 → 修复 → 测试 → 继续

不要因为 routine implementation blocker 把 Owner 变成 message relay。

---

## 17. ARCHITECTURE REVIEW GATE

以下情况必须停在 Architecture Review Gate：

1. 需要改变 InvestmentDecision / ExecutionMandate / ExecutionResult / PortfolioSnapshot / RiskPolicy contract；
2. 需要 Athena repo 修改；
3. 需要改变 Portfolio authority；
4. 需要新增任何交易写 API；
5. 需要让 UI 拥有交易控制能力；
6. 需要修改 scheduler / execution semantics；
7. 需要改变现有研究建议的投资权限含义；
8. 发现当前手工 Portfolio 与 Athena account truth 无法在不混淆事实源的情况下共存。

在 Gate 时：

把具体问题、可选方案、影响范围、推荐方案写进 PR / mission report。

不要自行跨过边界。

---

## 18. OWNER HARD STOP

以下任何事项立即停止：

- 真实资金
- LIVE trading
- 实盘权限
- 券商权限扩张
- SELL / REDUCE
- RiskPolicy 产品决策
- 投资决策权变化
- 认证 / 网络暴露扩大
- 不可逆数据库迁移
- 破坏性数据操作
- 任何把执行层变成投资判断层的变化

---

## 19. TEST / ACCEPTANCE

### BACKEND

至少覆盖：

1. decision scorecard list：
   - created_at DESC
   - pagination
   - symbol filter
   - action filter
   - mode filter
   - source_report_id filter
2. immutable scorecard parsing；
3. HOLD：
   - 没有 mandate 时列表仍正常；
   - UI summary 是“无需交易”；
4. BUY / ADD：
   - current / target / delta 正确；
5. execution result：
   - requested / submitted / filled / remaining 不混淆；
6. UNKNOWN：
   - 显示“状态待确认 / 待核对”；
   - 不显示“失败”；
7. BLOCKED：
   - submitted_quantity=0；
   - 正确展示 block reason；
8. Snapshot B：
   - 存在则展示；
   - 不存在不能 synthetic；
9. API auth behavior 与现有 read-only endpoint 一致。

### FRONTEND

至少覆盖：

10. Sidebar 新增“投资决策”；
11. 原“AI 建议”显示为“研究建议”；
12. `/decision-signals` 旧 URL 不失效；
13. `/investment-decisions` 正常 lazy route；
14. 默认中文主要界面中不得出现：
    - Single Brain
    - ResearchBundle
    - PortfolioSnapshot
    - RiskPolicy
    - InvestmentDecision
    - ExecutionMandate
    - ExecutionResult
    - Decision Scorecard
    - PENDING_RECONCILIATION
    - SIMULATION_EXECUTION
15. 决策卡正确区分：买入 / 加仓 / 持有；
16. HOLD 显示“本轮无需交易”；
17. BLOCKED 与 HOLD 不得混为一类；
18. UNKNOWN / pending reconciliation 明显可见；
19. Drawer deep link：`?decision=<id>` 刷新后仍能恢复；
20. 手机宽度下：决策卡和详情可正常阅读，不出现关键内容截断；
21. 投资决策页面不得发起任何交易 POST。

### REGRESSION

运行 repo 现有：

- Python focused tests
- architecture tests
- full pytest suite
- Web unit tests
- typecheck
- lint
- production build

如 repo 已有 E2E：运行与导航 / route / Drawer 相关 E2E。

不要只报告“我认为应该能工作”。

报告精确 test counts / command result。

---

## 20. MANUAL PRODUCT ACCEPTANCE

至少用真实 persisted M3 data 或 faithful read-only fixture 验证以下三种页面。

### A. HOLD

用户一眼看懂：

> 系统决定继续持有，没有交易。

### B. BUY / ADD + BLOCKED

用户一眼看懂：

> 系统决定买/加多少，但执行层因某个事实条件没有提交。

### C. BUY / ADD + UNKNOWN / reconciliation

用户一眼看懂：

> 交易状态还不能确定，系统正在等待核对，不会盲目重试。

如果当前持久化数据没有 UNKNOWN：允许用 frontend/backend test fixture 验证 UI。

禁止为了验收制造真实 broker mutation。

---

## 21. VISUAL ACCEPTANCE

新页面必须看起来像“原版 DSA 新增了一页”。

不是：

- Bloomberg 克隆
- 交易终端克隆
- Athena 管理台
- 工程监控面板

必须复用：

- 现有 spacing
- Card
- PageHeader
- Badge
- Drawer
- 按钮
- 字体层级
- 亮/暗主题
- 移动端布局

避免：

- 满屏 KPI
- 过多发光效果
- 过度红绿颜色
- 大面积工程字段
- 巨大 JSON dump

技术 JSON 如需展示，放在折叠的“技术详情”中。

---

## 22. MISSION DELIVERABLES

最终 Draft PR 应包括：

1. `docs/DSA_UI_ARCHITECTURE_V1.md`
2. 新“投资决策”导航和页面
3. 决策档案 Drawer
4. read-only scorecard list API
5. 必需 frontend API/types
6. “AI 建议”用户文案升级为“研究建议”
7. 中文状态映射
8. 完整 tests
9. 至少桌面 + 手机的 sanitized screenshots 或等价可审阅视觉证据
10. PR 描述中明确声明：
   - no trading authority change
   - no RiskPolicy change
   - no Athena authority change
   - no live trading change
   - no scheduler cadence change
   - no SELL/REDUCE
   - no transaction mutation from new UI

---

## 23. FINAL REPORT FORMAT

完成后不要只说“done”。

在 Draft PR 中报告：

```text
MISSION STATUS

Architecture:
PASS / BLOCKED

UI:
PASS / BLOCKED

Read-only API:
PASS / BLOCKED

Chinese-first copy:
PASS / BLOCKED

Responsive:
PASS / BLOCKED

Regression:
PASS / BLOCKED

Trading authority unchanged:
YES / NO

Athena repo changed:
YES / NO

Live trading changed:
YES / NO

SELL/REDUCE introduced:
YES / NO

HEAD SHA:
<exact SHA>

Tests:
<exact commands and counts>

Known limitations:
<exact remaining limitations>

Architecture review requested:
YES
```

---

## 24. MERGE BOUNDARY

本 Mission 授权：

- 开发
- 测试
- 调试
- 创建 branch/worktree
- 提交 commits
- 创建/更新 Draft PR
- 提交 sanitized review evidence

本 Mission **不授权**：

- merge
- production deployment
- live-trading related configuration changes

完成并达到 merge-ready 后：进入 **ARCHITECTURE REVIEW GATE**。

不要因为代码已经通过测试而自行 merge。

---

# MISSION SUCCESS CONDITION

用户打开 DSA 后：

- 仍然认得这是原来的 DSA；
- 原有功能没有消失；
- 原来的“AI 建议”被更准确地表达为“研究建议”；
- 左侧自然多出“投资决策”；
- 用户无需理解任何内部 contract 名称，就能回答：
  - 自动投资有没有运行？
  - 最近什么时候运行？
  - 系统研究了什么？
  - 系统最终决定买入、加仓还是持有？
  - 决定了多少数量？
  - 为什么？
  - 执行有没有发生？
  - 如果没发生，为什么？
  - 实际提交多少？
  - 实际成交多少？
  - 有没有状态待确认？
  - 决策前账户是什么样？
  - 决策后账户是什么样？

与此同时：

> UI 没有获得任何新的投资权或交易权。

这就是本 Mission 的 PASS。
