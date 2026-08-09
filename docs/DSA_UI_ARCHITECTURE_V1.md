# DSA UI Architecture v1

**Version:** 1.0
**Status:** Normative UI baseline
**Scope:** DSA Web product information architecture and read-only investment-decision presentation

This document freezes the first UI architecture for the integrated DSA/Athena product. It is subordinate to `SINGLE_BRAIN_CONSTITUTION.md`: UI is an observational projection and receives no research, investment, execution, risk-policy, or portfolio-truth authority.

## 1. Product shape

There is one user-facing product: DSA. Athena remains the account-fact and execution infrastructure beneath it; it does not receive a separate end-user UI.

The interface keeps DSA's existing Shell, Sidebar, PageHeader, Card, Drawer, Badge, StatusDot, theme, spacing, and responsive language. The home page remains a research workspace, not a trading terminal.

## 2. Primary navigation

The v1 navigation baseline is:

1. 首页
2. 问股
3. 选股
4. 持仓
5. 研究建议
6. 投资决策
7. 回测
8. 告警
9. 用量
10. 设置

“决策档案” is the detail view of “投资决策”, not a primary navigation item.

## 3. Information authority

| User surface | Question answered | Authoritative source | Explicit limit |
| --- | --- | --- | --- |
| 股票分析 / 研究建议 | 这只股票怎么看？ | DSA Research and existing analysis results | Never decides account allocation or execution quantity. |
| 投资决策 | 结合账户，我应该怎么做？ | DSA `InvestmentDecision` and its immutable scorecard lineage | Read-only; never changes or recomputes the decision. |
| 决策前/后账户 | 当时账户事实是什么？ | Scorecard's Athena-authored Snapshot A/B | Never synthesized from fills or written into the manual portfolio ledger. |
| 执行情况 | Athena 实际提交/成交/阻止了什么？ | Canonical `ExecutionResult` lineage | UNKNOWN remains uncertain and never implies retry. |
| 持仓 | 账户与持仓中心 | Manual DSA account today; future connected-account view uses Athena snapshots | Manual and connected facts must remain visibly and technically distinct. |

UI must not calculate final quantities, infer missing account truth, modify RiskPolicy, construct a mandate, dispatch an order, retry execution, or mutate portfolio state.

## 4. Product language

Primary Chinese UI uses the following terms. Contract names may appear only in collapsed technical detail.

| Internal term | Primary UI term |
| --- | --- |
| Single Brain / M3 runtime | 自动投资 |
| ResearchBundle | 研究依据 |
| PortfolioSnapshot / Snapshot A / Snapshot B | 账户快照 / 决策前账户 / 决策后账户 |
| RiskPolicy | 风险约束 |
| InvestmentDecision | 投资决策 |
| ExecutionMandate | 执行指令 |
| ExecutionResult | 执行结果 |
| Decision Scorecard | 决策档案 |
| SIMULATION_EXECUTION | 模拟交易 |

Actions: BUY=买入, ADD=加仓, HOLD=持有. Execution states: FILLED=已成交, PARTIALLY_FILLED=部分成交, ACCEPTED=已接受, ACTIVE=挂单中, BLOCKED=已阻止, BROKER_REJECTED=券商拒绝, EXPIRED=已过期, CANCELLED=已取消, UNKNOWN=状态待确认. Reconciliation states: PENDING_RECONCILIATION=待核对, RECONCILED=已核对, DEGRADED=核对受限, NOT_REQUIRED=无需核对.

“研究建议” must visibly explain: “这里展示的是股票研究观点，不代表账户实际交易。” The existing `/decision-signals` route and features remain intact.

## 5. Status and color semantics

Color communicates operational state, never investment direction.

- BUY / ADD use info; HOLD uses default.
- Healthy runtime, FILLED, and RECONCILED use success.
- ACCEPTED, ACTIVE, and PARTIALLY_FILLED use info.
- BLOCKED, EXPIRED, PENDING_RECONCILIATION, and UNKNOWN use warning.
- BROKER_REJECTED or a confirmed execution failure uses danger.
- CANCELLED uses default.

UNKNOWN is prominent but must not be called success or failure.

## 6. Investment decisions page

Route: `/investment-decisions`.

The page header is “投资决策” with “查看自动投资的决策、执行情况和账户变化。” It contains:

1. A read-only automatic-investment status area based only on readiness facts: enabled/running state, simulation mode, last run, next expected run, pending reconciliation count, and latest account snapshot time.
2. A newest-first decision timeline, default-filtered to `SIMULATION_EXECUTION` so historical shadow scorecards do not contaminate the current operating view.
3. Pagination and deterministic filters supported by the immutable scorecard list endpoint.

Each decision card separates the Brain decision from execution:

- BUY / ADD: current X → target Y; this change Z.
- HOLD: current X → target X; “继续持有，本轮无需交易。”
- Decision confidence is shown as the immutable Brain output, distinct from research confidence.
- Requested, submitted, filled, and remaining quantities remain separate.
- BLOCKED describes why execution submitted zero; it never labels the investment decision itself a failure.

The page performs GET requests only and exposes no mutation or retry controls.

## 7. Decision archive drawer and deep links

“查看决策档案” opens the existing right-side Drawer. Desktop uses a right drawer; mobile uses the same responsive Drawer language at near-full width.

The fixed user order is:

1. 研究依据
2. 决策前账户
3. 风险约束
4. 投资决策
5. 执行情况
6. 决策后账户

Snapshot A and B are displayed only when present in the immutable scorecard. Missing Snapshot B is shown as “尚无决策后账户快照”; it is never calculated from Snapshot A and fills.

Position facts match the decision instrument by the exact canonical `(market, symbol)` pair. Monetary facts display the snapshot's canonical `currency`; the UI never assumes CNY or converts values.

The recoverable URL is `/investment-decisions?decision=<decision_id>`. Refresh restores the same drawer when the ID exists; closing removes only the `decision` query parameter and returns to the list.

Technical IDs, hashes, producer/model identifiers, and raw JSON are hidden by default inside a “技术详情” disclosure.

## 8. Read-only backend projection

- Existing detail: `GET /api/v1/decision-scorecards/{decision_id}` remains unchanged.
- New list: `GET /api/v1/decision-scorecards` reads only `single_decision_scorecards`, newest first, with pagination and exact filters for symbol, action, mode, and source report.
- Readiness: `GET /api/v1/single-brain/m2/readiness` remains the compatible runtime-fact source despite its historical path name.

If a summary field has no canonical source it is `null`. The list and detail parser validate the persisted immutable scorecard and hash before projection.

## 9. Cross-page relationships

The product flow is:

- 首页 → 股票分析
- 股票分析 → 研究建议
- 研究建议 → 投资决策
- 投资决策 → 决策档案
- 投资决策 → 持仓
- 持仓 → 股票分析 / 研究建议 / 投资决策

Links between research and investment decisions require an exact `source_report_id` or `decision_id`. Symbol similarity or fuzzy matching is not lineage and must not create a link.

## 10. Portfolio future baseline

“持仓” becomes the single account and holdings center in a later phase.

- Manual accounts retain current DSA account creation, manual trade, cash flow, CSV, dividend, and split features.
- Connected accounts use Athena authoritative PortfolioSnapshot as fact truth and are read-only in DSA. DSA must not overwrite broker facts, delete broker trades, or copy snapshots into the manual portfolio ledger.

This v1 mission does not implement that unification.

## 11. Deferred phases

- Unified connected-account and manual-account presentation in 持仓.
- 首页 “今日投资动态”.
- Richer deterministic 研究建议 ↔ 投资决策 navigation.
- Alert/backtest relationships to real investment decisions.
- Long-horizon outcome evaluation beyond immediate execution diagnostics.

None of these deferred items grants UI transaction authority.

## 12. Sanitized review evidence

Faithful read-only fixtures cover HOLD, ADD + BLOCKED, and BUY + UNKNOWN without broker or portfolio mutation:

- `docs/assets/dsa-investment-decisions-v1-desktop.jpg`
- `docs/assets/dsa-investment-decisions-v1-drawer.jpg`
- `docs/assets/dsa-investment-decisions-v1-mobile.png`

The browser acceptance test also proves every request to the scorecard and readiness surfaces uses GET.
