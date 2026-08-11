# DSA 今日总览 v1

## 产品职责

DSA 首页默认显示“今日总览”，并保留原有“研究工作台”。今日总览只组合已有事实，帮助用户快速查看已连接账户、当前持仓、今日研究、投资决策、自动投资状态、今日动态和需要关注的事项。

今日总览不是新的决策引擎、账户账本或交易控制台。

## 事实来源

| 页面信息 | 事实来源 | 失败语义 |
| --- | --- | --- |
| 账户与持仓 | `GET /api/v1/portfolio/connected-snapshot` | 明确显示已连接账户不可用；不补零，不回退到手工账户 |
| 今日研究 | 现有分析历史、任务和观察列表数据 | 仅该分区显示不可用；研究观点不表述为投资决策 |
| 投资决策与执行状态 | `GET /api/v1/decision-scorecards?mode=SIMULATION_EXECUTION` | 仅展示 authoritative M3 simulation-execution scorecard；HOLD、BLOCKED、UNKNOWN 保持不同语义 |
| 自动投资状态 | `GET /api/v1/single-brain/m2/readiness` | 显示状态需要关注；不推断 scheduler 或执行事实 |

所有分区独立加载。任一来源失败不会清空其他已经确认的事实。

## 运行原因可解释性

Readiness 在原有 cycle/symbol/M3 checkpoint 事实之上追加只读
`latest_cycle_diagnostics` 投影；它不是新的运行状态表。该投影只返回：

- 最新 cycle 的终态、失败阶段和稳定安全原因代码；
- research、InvestmentDecision、ExecutionMandate 是否已由现有持久化事实证明产生；
- broker submission 是已记录、明确为零，还是仍属 UNKNOWN；
- 不包含原始异常、provider secret、账户标识或 stack trace。

`FAILED_CLOSED` 是一等 cycle 结果：scheduler authority 健康时，“自动投资”继续显示
“运行中”，最近一轮显示“本轮安全停止”。它不是 HOLD、执行 BLOCKED、执行 UNKNOWN，
也不是 scheduler 停止。

安全原因只在持久化证据明确时映射为有限中文词汇，例如“AI 分析额度不足”、
“AI 分析服务暂时不可用”或“账户快照已过期”。证据不足时固定显示
“研究阶段未完成，具体原因待确认”，不得从历史背景猜测 provider 或额度原因。

当最新一轮在 decision 之前 fail closed 时，今日总览会明确显示没有生成新的
InvestmentDecision、ExecutionMandate 或 broker submission。今天较早的有效研究和决策
继续显示，不会被最近一次失败覆盖；执行侧 UNKNOWN / pending reconciliation 仍作为独立
关注事项呈现。

## 权限边界

- 已连接账户继续以 Athena authoritative `PortfolioSnapshot` 为账户事实；DSA 不写入手工 portfolio ledger。
- 持仓 identity 使用精确 `(market, symbol)`；金额使用 Snapshot 自带 `currency`。
- 研究卡片只显示研究观点。最终 BUY / ADD / HOLD 和数量只来自 `InvestmentDecision` / Decision Scorecard。
- “执行指令已生成”只在 Decision Scorecard 已记录请求数量时显示；HOLD 显示本轮无需生成，字段缺失时显示“未记录”，不从研究观点或目标数量猜测。
- HOLD 是中性决策；BLOCKED 是执行条件未满足；UNKNOWN 显示“状态待确认”并使用 warning 语义。
- 健康的 M3 simulation runtime 使用 `execution_mode=SIMULATION_EXECUTION`、`execution_authorization=ON` 与 scheduler mode `M3_SIMULATION_EXECUTION_ONLY`；这里的 ON 仅表示已授权现有 simulation execution，不代表 LIVE 权限。
- 今日动态中的 HOLD 使用 neutral；BLOCKED / UNKNOWN 使用 warning；ACCEPTED / ACTIVE / PARTIALLY_FILLED 使用 info；FILLED 使用 success；BROKER_REJECTED 使用 danger。
- 今日总览不创建 `ExecutionMandate`、不重试、不撤单、不核对、不提交订单，也不修改 RiskPolicy 或 PortfolioSnapshot。

## 导航与发现性

- 首页内部模式：默认“今日总览”，可切换到完整“研究工作台”。
- “查看全部持仓”链接到 `/portfolio?account=connected`。
- `/portfolio` 支持 `account=connected`、`account=all` 和手工账户 ID；没有参数且 connected snapshot 可用时，默认显示已连接账户。
- 投资决策链接到 `/investment-decisions?decision=<decision_id>`，复用现有权威决策档案。

## 已知限制

- 今日动态只合并带可靠时间戳的现有账户、研究、决策和周期事实；不会补齐缺失事件或推断因果关系。
- 当前研究历史没有统一 canonical market 字段时，首页不会猜测市场。
- 今日总览不计算合约中不存在的“当日盈亏”。
- 历史 cycle 若只保存了泛化失败文本，readiness 只能返回“具体原因待确认”；新失败会把
  `AnalysisResult` 的错误归一为稳定安全类别，但不会保存或展示原始 provider 错误。

## Sanitized 视觉证据

- `assets/dsa-daily-overview-v1-desktop.png`：desktop 今日总览与 connected account。
- `assets/dsa-daily-overview-v1-holdings.png`：精确 `(market, symbol)` 持仓、Snapshot currency 与账户深链。
- `assets/dsa-daily-overview-v1-decisions.png`：HOLD / BLOCKED / UNKNOWN、执行指令与券商提交事实。
- `assets/dsa-daily-overview-v1-mobile.png`：390px 移动端优先顺序与可读性。
- `assets/dsa-daily-overview-v1-connected-unavailable.png`：connected snapshot 不可用时的独立降级，不补零。
- `assets/dsa-daily-overview-v1-research-workbench.png`：原研究工作台保留。
- `assets/dsa-daily-overview-v1-connected-portfolio.png`：`/portfolio?account=connected` 深链。
- Playwright PR artifact `runtime-reason-failed-closed-known.png`：健康 scheduler + 已知安全原因。
- Playwright PR artifact `runtime-reason-failed-closed-unknown.png`：未知原因不猜测 provider/额度。
- Playwright PR artifact `runtime-reason-history-preserved.png`：较早研究/决策在后续 fail closed 后仍保留。
- Playwright PR artifact `runtime-reason-failed-closed-mobile.png`：390px 失败原因与零执行事实可读。

所有 fixture 都使用 sanitized account、broker、snapshot 与 lineage 标识，不包含真实账户信息或凭据。
