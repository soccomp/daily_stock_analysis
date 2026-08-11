# DSA Daily Overview v1 Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this mission integrates DSA home, connected portfolio truth, research activity, investment decisions, and runtime readiness. It is a cross-surface product-integration task with important Single Brain semantics, but it does not require a cross-repo architectural rewrite or a new trading authority model.

---

## Mission Name

**DSA 今日总览 v1 — 让用户看见 Single Brain 每天在做什么**

## Base

Start from the latest `origin/athena-integration`.

At mission creation time the canonical branch is based on PR #10 merge commit:

`055ebac67f9d1700400ec4baec3804f296b6da1f`

Codex must fetch the latest remote state before starting and record the exact base SHA used for its branch/worktree.

---

## Product Problem

The system already has the core Single Brain runtime pieces:

- Athena authoritative simulation PortfolioSnapshot
- DSA research / analysis / history / watchlist
- Single Brain InvestmentDecision
- ExecutionMandate / ExecutionResult
- Decision Scorecard
- M3 recurring scheduler

But the user cannot easily answer basic daily questions from the DSA product:

- What do I currently hold?
- What did the system research today?
- What did the Brain decide?
- Was anything actually submitted?
- Why was nothing submitted?
- Is the system healthy?
- Is there anything that needs attention?

The backend is working, but the product does not yet expose a coherent daily operating picture.

This mission creates a **read-only daily investment dashboard inside the existing DSA home experience**.

---

## Core Doctrine

**Single Brain, Single Decision, Single Scorecard.**

The UI must not create a second interpretation layer.

Authoritative data sources remain:

- Portfolio truth: Athena authoritative connected snapshot through existing DSA ingress/API
- Research truth: existing DSA analysis/history/task/watchlist data
- Investment truth: existing Decision Scorecards
- Runtime truth: existing Single Brain readiness state

The UI may summarize existing facts, but must never invent portfolio, research, decision, execution, or chronology facts.

---

## Primary Acceptance Goal

A user who knows nothing about the backend architecture should be able to open the DSA home page and, within about 10 seconds, correctly answer:

1. How much money is in the authoritative connected account?
2. What stocks are currently held?
3. What stocks did the system research today?
4. What were the research views?
5. What investment decisions did the Brain make today?
6. Was any trade actually submitted?
7. If not, why not?
8. When did the latest automatic-investment cycle finish?
9. When is the next cycle expected?
10. Is the system currently healthy?
11. Is there anything that requires attention?

If these questions cannot be answered clearly from the home surface, the mission is not complete.

---

# 1. Home Product Structure

Preserve all existing HomePage research functionality.

Do **not** delete, replace, or materially degrade:

- stock search
- analysis submission
- watchlist
- task panel
- today's analyses
- market review
- report reading
- report history
- research workflow

Add two internal home modes/tabs:

- **今日总览**
- **研究工作台**

Default home mode:

**今日总览**

The current HomePage research experience becomes **研究工作台** and remains fully available.

Do not add a new top-level navigation item for 今日总览.

---

# 2. Authoritative Account Summary

Use the existing connected-account API, preferably:

`GET /api/v1/portfolio/connected-snapshot`

Do not access Athena directly from the browser.

The first screen of 今日总览 must contain a clearly visible account summary showing authoritative connected-account facts:

- 账户权益
- 现金合计
- 可用现金
- 冻结现金
- 已实现盈亏
- 未实现盈亏
- 持仓数量
- 币种
- 快照时间
- 核对状态
- 数据质量

Only use fields that exist in the authoritative snapshot.

Do not fabricate daily PnL if the contract does not provide a true daily PnL field.

If connected snapshot is unavailable:

- show an explicit unavailable state
- do not show zero balances as fallback
- do not silently fall back to manual portfolio data

---

# 3. Current Holdings Must Be Immediately Visible

The user has already verified that the authoritative Athena simulation account currently contains real connected holdings. The product must make connected holdings discoverable without requiring knowledge of internal account selectors.

今日总览 must show a compact **当前持仓** section from the authoritative connected snapshot.

Display at least:

- 市场
- 股票代码
- 数量
- 可用数量 if useful and space permits
- 最新价
- 市值
- 未实现盈亏

Identity must remain exact by:

`(market, symbol)`

Never merge positions by symbol alone.

Currency must come from the authoritative snapshot; never hard-code CNY.

Show a deterministic top subset, approximately 5–8 positions, using a stable rule such as market value descending.

Show a clear count:

`共 N 项持仓`

And a CTA:

**查看全部持仓**

This CTA must deep-link to:

`/portfolio?account=connected`

---

# 4. Portfolio Discoverability Fix

Current PortfolioPage behavior hides the connected account too easily because the default selection can remain manual/all.

Implement URL-driven account selection support:

- `/portfolio?account=connected`
- `/portfolio?account=all`
- `/portfolio?account=<manual-account-id>`

When there is no account query parameter:

- if an authoritative connected account is available, default to **已连接账户**
- otherwise preserve sensible existing manual/all behavior

If an explicit persisted user preference already exists and is appropriate, it may be respected, but connected account must never remain effectively undiscoverable.

Connected and manual balances must never be silently aggregated.

---

# 5. Automatic Investment Runtime Status

今日总览 must contain a prominent but calm **自动投资状态** section using existing Single Brain readiness data.

At minimum show:

- 自动投资：运行中 / 需要关注 / 未运行
- 当前模式：模拟交易
- 最近一次运行时间
- 最近一次运行结果
- 下一次预计运行时间
- 待核对事项
- 最近账户快照时间

Use normal product language.

Do not foreground internal names such as:

- `M3_SIMULATION_EXECUTION_ONLY`
- scheduler internal IDs
- authority_count

Internal runtime details may appear under collapsed technical details if useful.

---

# 6. 今日研究

The user must be able to see what research the system actually performed today.

Reuse existing DSA research/history/task/watchlist data. Do not create a new research database.

Show a **今日研究** summary with at least:

- 今日已完成分析 N 项
- 正在分析 N 项
- 观察列表今日覆盖 X / Y, if this is already reliably available
- 最近市场复盘时间, if available

Then show the most recent 5–10 research items for today.

Each item should use existing factual fields where available:

- 股票代码 / 名称
- 市场 if reliably known
- 完成时间
- 研究观点 / action label
- confidence or sentiment where it already exists
- concise existing summary / operation advice / market phase summary when reliable

Clicking a research item should open the existing research/report experience rather than creating a second report viewer.

Critical semantic rule:

**Research output is 研究观点, not 投资决策.**

Research has interpretation authority over the asset, not capital-allocation authority over the account.

---

# 7. 今日投资决策

Reuse existing Decision Scorecard list/readiness APIs, preferably existing `investmentDecisionsApi.list` and `investmentDecisionsApi.readiness`.

Show the latest decisions from today, approximately up to 5 items.

Each item should contain factual fields such as:

- 时间
- 股票
- 买入 / 加仓 / 持有
- 当前数量 → 目标数量
- delta quantity
- concise rationale
- execution status

Semantics:

- HOLD is neutral and must not be represented as blocked or failed
- BLOCKED is different from HOLD
- UNKNOWN = `状态待确认`
- UNKNOWN uses warning semantics, never success or confirmed-failure danger semantics

Clicking a decision must deep-link into the existing authoritative decision detail:

`/investment-decisions?decision=<decision_id>`

Do not duplicate DecisionScorecardDrawer logic on the home page.

---

# 8. 今日动态 Timeline

Add a read-only **今日动态** timeline that helps the user understand what happened.

Possible factual event types include:

- research completed
- InvestmentDecision created
- mandate created
- execution BLOCKED / ACCEPTED / FILLED
- authoritative snapshot updated
- cycle completed / failed

Example product-language mappings may look like:

- `08:00 自动投资完成本轮分析`
- `08:03 贵州茅台：研究完成`
- `08:05 贵州茅台：决定加仓 900 股`
- `08:05 市场休市，交易未提交`
- `08:06 账户事实已重新核对`

But these are examples only.

Every timeline item must be derivable from real existing timestamps/statuses.

Do not invent event ordering when the system cannot prove the chronology.

If chronology cannot be safely merged, show grouped factual blocks instead of manufacturing a total order.

---

# 9. 需要关注

Add a dedicated **需要关注** section.

Normal state:

`目前没有需要处理的事项`

Show attention items only when supported by real facts, for example:

- connected snapshot unavailable
- stale snapshot
- pending reconciliation
- UNKNOWN state
- scheduler authority count not equal to 1
- runtime cycle failed
- research service unavailable

Color doctrine:

- normal / reconciled / filled = success where appropriate
- active / accepted = info
- pending / stale / unknown = warning
- confirmed failure / broker rejected = danger

UNKNOWN is never danger.

---

# 10. Research / LLM Fail-Closed Visibility

The product should make a fail-closed research cycle understandable to the user.

If existing APIs/diagnostics can reliably prove that research did not complete due to provider/quota/runtime failure, show a user-facing statement similar to:

**本轮研究未完成，因此没有生成新的投资指令。**

Provider names, raw errors, quota diagnostics, and technical stack details belong under technical details, not the main surface.

If current APIs do not contain enough reliable information:

- do not guess
- first audit task/readiness/scorecard diagnostics
- if truly needed, implement the smallest possible DSA read-only status API extension

Any backend semantic/API extension is subject to the Architecture Review Gate and must remain observational only.

No runtime control API may be added.

---

# 11. Holdings + Research Relationship

The home dashboard may visually show that a currently held stock had a research update today, for example:

- 贵州茅台
- 持仓 300 股
- 今日研究：已完成

This is a visibility relationship only.

Never infer investment causality from that relationship.

The UI must not claim:

- “because this is held, the Brain bought it”
- “because research is positive, the account should add”

Investment reasons come only from authoritative InvestmentDecision / Scorecard data.

---

# 12. Design Requirements

Build naturally on the existing DSA product and design grammar.

Reuse existing primitives wherever possible:

- Card
- Badge
- InlineAlert
- PageHeader / AppPage patterns where appropriate
- Drawer
- EmptyState
- spacing
- typography
- radius
- responsive behavior

Do not redesign DSA into a separate dark quant terminal.

Do not present Athena as an equal user-facing product.

Main product language should say:

- 已连接账户
- 账户快照
- 当前持仓
- 自动投资
- 今日研究
- 投资决策
- 执行状态
- 待核对
- 状态待确认

Athena may appear as a source or in technical details when appropriate.

Chinese-first visible UI.

---

# 13. Mobile Requirements

At approximately 390px width the dashboard must remain readable and usable.

Preferred mobile information order:

1. 自动投资状态
2. 账户概览
3. 需要关注
4. 今日投资决策
5. 今日研究
6. 今日动态

Holdings should use a compact list/card treatment or a well-contained horizontal scroll. Do not make the entire page overflow horizontally.

---

# 14. Read-Only Boundary

All new 今日总览 functionality is observational/read-only.

Do not add:

- buy button
- add-position button
- HOLD control
- retry execution
- cancel order
- manual reconcile
- force analysis
- manual execution
- RiskPolicy editor
- LIVE switch

Existing research-workbench analysis triggers may remain because they are existing product behavior, but do not expand their authority.

---

# 15. Implementation Strategy

Audit existing APIs before creating new backend code.

Prefer reuse of:

- `portfolioApi.getConnectedSnapshot`
- `investmentDecisionsApi.list`
- `investmentDecisionsApi.readiness`
- existing history/task/watchlist APIs and hooks

Prefer frontend composition when it preserves semantics and consistency.

Do not create a large backend aggregation layer merely for convenience.

A minimal read-only aggregation/status endpoint is allowed only if frontend composition would create a real consistency, performance, or semantic problem.

If backend API semantics are changed or extended, document the reason clearly in the PR and flag it for Architecture Review.

---

# 16. Failure Isolation

One dashboard source failing must not blank the entire home page.

For example:

- portfolio unavailable must not hide research
- research unavailable must not hide portfolio truth
- decision API unavailable must not hide account facts
- readiness unavailable must show a scoped runtime-status error, not destroy the whole page

Each major section should have independent loading/error/empty states.

Never convert missing/unavailable data into fabricated zero values.

---

# 17. Testing Requirements

At minimum cover:

- home connected snapshot visibility
- holdings count and top holdings
- `(market, symbol)` identity preservation
- snapshot currency is not hard-coded
- connected unavailable does not fall back to zero/manual
- research and investment-decision semantics remain distinct
- HOLD != BLOCKED
- UNKNOWN renders warning / 状态待确认
- `/portfolio?account=connected` deep-link
- connected-account default discoverability
- manual-account workflows preserved
- dashboard source failure isolation
- empty states
- mobile layout
- research-workbench preserved

Run as applicable:

- focused frontend tests
- full frontend tests
- build
- lint
- backend tests if backend touched
- focused portfolio tests
- focused investment-decision tests
- Playwright desktop
- Playwright mobile
- `git diff --check`

If backend source is changed, run the relevant backend architecture/authority/full regression gates appropriate to scope.

---

# 18. Visual Evidence

Produce sanitized visual evidence for at least:

- 今日总览 desktop
- 今日总览 mobile
- connected holdings/account facts visible
- HOLD vs BLOCKED presentation
- degraded / UNKNOWN presentation
- connected unavailable presentation
- preserved 研究工作台
- `/portfolio?account=connected`

No screenshot may expose sensitive account identifiers or secrets.

---

# 19. Autonomous Blocker Policy

**AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE**

Routine blockers are not hard stops.

Codex should autonomously diagnose/fix/test/continue for issues such as:

- TypeScript
- CSS/layout
- routing
- mocks/fixtures
- test failures caused by the mission changes
- Playwright
- build
- lint
- stale local artifact
- ordinary API mapping
- reversible local dev/runtime configuration

Do not ask the Owner to relay routine implementation details.

---

# 20. Architecture Review Gate

Stop for Architecture Review before merge when the implementation is complete.

This is especially important if the mission introduces or changes:

- read-only API contract semantics
- cross-domain aggregation semantics
- new shared data model
- home/runtime status mapping that could alter product meaning

Architecture Review is performed on the exact GitHub PR HEAD.

---

# 21. Owner Hard Stop

Stop and require Owner decision if any solution requires:

- changing investment authority
- changing sizing/capital allocation
- changing RiskPolicy product decisions
- adding SELL / REDUCE
- adding execution/trading controls
- enabling LIVE
- expanding broker permissions
- expanding authentication/network exposure
- destructive migration/data deletion
- removing or replacing existing research functionality
- changing Athena source/runtime to make the UI work

Do not work around these boundaries.

---

# 22. Git Workflow

1. Fetch latest `origin/athena-integration`.
2. Record the exact base SHA.
3. Create a separate feature branch/worktree.
4. Implement the mission.
5. Test and fix routine blockers autonomously.
6. Commit.
7. Push.
8. Open a **Draft PR** targeting `athena-integration`.
9. Put exact HEAD SHA, test evidence, visual evidence, authority-boundary statement, and known limitations in the PR.
10. Stop at **ARCHITECTURE REVIEW GATE**.

Do **not** merge.

Do **not** deploy.

No merge or deployment authorization is implied by this Mission.

---

## Final Acceptance Checklist

The mission is complete only if the home experience clearly and truthfully answers all of the following without requiring the user to inspect backend logs:

- [ ] 当前账户权益 / 现金是什么？
- [ ] 当前权威持仓是什么？
- [ ] 今天研究了什么？
- [ ] 研究观点是什么？
- [ ] Brain 今天做了什么投资决策？
- [ ] 是否产生执行指令？
- [ ] 是否真的向 broker 提交？
- [ ] 如果没有提交，为什么？
- [ ] 最近一轮什么时候结束？
- [ ] 下一轮预计什么时候开始？
- [ ] 当前系统是否健康？
- [ ] 是否有需要关注的事项？
- [ ] connected/manual authority separation preserved
- [ ] no synthetic portfolio truth
- [ ] no synthetic execution truth
- [ ] no new trading authority
- [ ] existing research workbench preserved
- [ ] mobile usable
- [ ] exact GitHub PR HEAD reported for Architecture Review
