# DSA Runtime Reason Explainability v1 Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this mission crosses Single Brain readiness semantics, research-cycle observability, and the Daily Overview product surface. It requires careful fail-closed interpretation, but it does not authorize a new investment architecture, execution authority, or cross-repo rewrite.

---

## Mission Name

**DSA 运行原因可解释性 v1 — 让用户知道“为什么这一轮没有产生决策”**

## Base

Start from the latest `origin/athena-integration`.

At mission creation time the canonical branch head is:

`432e36d57a6cc2ba1c901acc48e482ffc0a8e69a`

That branch contains the merged Daily Overview v1 application code and its deployment-governance document.

Codex must fetch remote state before starting and record the exact base SHA used for its branch/worktree.

---

# Product Problem

Daily Overview v1 is deployed and now correctly exposes what the system did or did not do.

The real M5 deployment revealed an important observability gap:

- the recurring scheduler is still healthy and running
- the latest natural cycle can end in the fail-closed state `FAILED_CLOSED`
- there may be no current-day research, no new InvestmentDecision, and no new ExecutionMandate
- the current UI does not understand `FAILED_CLOSED` as a first-class cycle outcome and conservatively renders it as `状态待确认`

This is safe but not sufficiently explanatory.

A user should not have to infer the causal chain from logs.

The product should be able to say, when supported by real runtime facts:

**本轮研究未完成。**

**原因：AI 分析额度不足 / 分析服务暂不可用 / 其他已确认的安全失败原因。**

**因此：本轮没有生成新的投资决策，也没有产生新的交易指令。**

**自动投资调度仍在运行，下次预计：<time>.**

The exact wording and reason must be evidence-backed. Never guess a provider, quota condition, failure cause, or causal chain that the runtime cannot prove.

---

# Core Doctrine

**Single Brain, Single Decision, Single Scorecard.**

This mission adds observability only.

It must not change:

- Research authority
- Brain investment authority
- sizing / allocation logic
- RiskPolicy
- PortfolioSnapshot semantics
- ExecutionMandate semantics
- ExecutionResult semantics
- Athena behavior
- broker behavior
- scheduler cadence
- execution permissions

A failed research cycle must remain fail closed.

No UI improvement may turn an incomplete research cycle into a decision, mandate, retry, or trade.

---

# Primary Acceptance Goal

When the latest automatic-investment cycle did not complete normally, the DSA home page should answer, from real facts:

1. Is the scheduler itself still running?
2. Did the latest cycle complete, fail closed, fail, or remain in progress?
3. At what stage did the cycle stop, if known?
4. What user-safe reason is known?
5. Was research completed?
6. Was a new InvestmentDecision created?
7. Was an ExecutionMandate created?
8. Was anything submitted to the broker?
9. Is there any pending reconciliation / UNKNOWN state?
10. When is the next scheduled run?
11. Does the user need to do anything?

The user should not have to open logs or technical IDs to understand a normal fail-closed outcome.

---

# 1. First Audit Existing Runtime Facts

Before changing source, inspect the existing path that produces and exposes cycle state.

Audit at minimum:

- recurring scheduler state
- latest cycle state / status
- M2/M3 operational repositories
- Single Brain readiness service / schema / API
- research task / provider / LLM failure diagnostics already persisted or exposed
- scorecard presence/absence for a failed cycle
- existing error-category or failure-reason fields
- existing sanitized user-facing error mappings

Determine whether the runtime already has enough reliable facts to distinguish cases such as:

- completed normally
- currently running
- fail-closed because research did not complete
- provider quota/rate-limit condition
- provider unavailable / transient service failure
- data/research prerequisite unavailable
- internal cycle failure
- execution-side UNKNOWN / pending reconciliation

Do not introduce a new diagnostic model until this audit proves it is needed.

---

# 2. Make `FAILED_CLOSED` a First-Class Cycle Outcome

The Daily Overview must explicitly recognize the real cycle status `FAILED_CLOSED`.

Do not map it to generic unknown merely because the UI previously lacked the enum/value.

Product semantics:

- scheduler healthy + latest cycle `FAILED_CLOSED` = **scheduler still running, latest cycle safely stopped**
- this is not the same as scheduler failure
- this is not the same as HOLD
- this is not the same as BLOCKED execution
- this is not the same as UNKNOWN execution
- this is not a successful cycle

Recommended user-facing presentation:

- scheduler badge remains `运行中` when scheduler authority/health is normal
- latest-cycle result becomes something like `本轮安全停止` / `本轮研究未完成`
- `需要关注` receives a warning item when the fail-closed condition is current/relevant

Do not render `FAILED_CLOSED` as danger unless the underlying confirmed reason is a genuine platform failure that existing product doctrine already maps to danger.

Fail-closed should normally use warning semantics.

---

# 3. Separate Scheduler Health from Latest-Cycle Outcome

The current dashboard must not collapse these two different facts into one status.

Example healthy-but-fail-closed state:

- 自动投资：`运行中`
- 最近一轮：`本轮研究未完成`
- 原因：`AI 分析额度不足` (only if proven)
- 新投资决策：`未生成`
- 交易指令：`未生成`
- 券商提交：`0`
- 下次预计：`12:00`

This state is valid and expected under fail-closed design.

Do not show `自动投资：未运行` merely because the latest cycle failed closed.

Do not show a green “everything completed” state when the latest cycle did not complete.

---

# 4. Explain the Failure Reason Using Evidence Only

If existing runtime data already exposes a reliable reason, map it into a user-safe reason category.

Prefer a small stable vocabulary, but derive it from actual existing runtime facts rather than inventing categories first.

Possible user-facing examples, only when evidence supports them:

- `AI 分析额度不足`
- `AI 分析服务暂时不可用`
- `研究所需数据暂时不可用`
- `研究阶段未完成`
- `运行过程中发生错误`

Main UI must not expose:

- raw stack traces
- tokens / credentials
- provider secrets
- account identifiers
- raw exception dumps
- internal filesystem paths

Technical details may show a sanitized provider/error code if already available and safe.

If the exact cause is not reliably known, show:

**研究阶段未完成，具体原因待确认。**

Do not guess quota exhaustion from historical context alone.

---

# 5. Minimal Read-Only Readiness Extension — Only If Needed

If the existing readiness API does not expose enough reliable facts, implement the smallest observational extension necessary.

Preferred shape is to extend the existing readiness projection rather than create a second runtime truth source.

Any new fields should be read-only and derived from already-persisted runtime facts.

Examples of useful concepts, subject to actual repository semantics:

- latest cycle terminal status
- failure stage
- safe failure category/code
- sanitized failure summary
- whether research completed
- whether decision was created
- whether mandate was created

Do not add fields merely because they are convenient for UI rendering.

Do not persist a duplicate operational state if the canonical fact already exists elsewhere.

If a backend semantic/API extension is required, this remains within the mission but is automatically subject to the final **ARCHITECTURE REVIEW GATE**.

---

# 6. Daily Overview — Automatic Investment Status

Upgrade the existing `自动投资状态` section.

When latest cycle is normal:

Preserve existing behavior.

When latest cycle is fail closed:

Show a compact explanation directly in the card, for example:

**本轮研究未完成**

`系统已安全停止本轮流程，没有生成新的投资决策或交易指令。`

Then show, when supported:

- `原因 · AI 分析额度不足`
- `最近运行 · <time>`
- `下次预计 · <time>`
- `待核对事项 · 0 项`

The copy must distinguish:

- scheduler continues to operate
- this specific cycle did not complete
- no trade was produced because the upstream research/decision path stopped

Do not imply that the user must intervene if the system will naturally retry at the next scheduled cycle and no Owner action is required.

---

# 7. Daily Overview — `需要关注`

For a current fail-closed cycle, show one clear warning item rather than generic `状态待确认` noise.

Example:

**最近一轮研究未完成**

`AI 分析额度不足；本轮未生成投资决策或交易指令。系统将在下一计划周期继续运行。`

Only use the quota-specific wording if proven by runtime data.

If no exact reason is known:

`最近一轮研究未完成；本轮未生成投资决策或交易指令。具体原因待确认。`

If there are also execution-side UNKNOWN or pending-reconciliation items, those remain separate attention items and must not be conflated with research fail-closed.

---

# 8. Daily Overview — 今日研究

When there are zero completed current-day research items because the latest cycle failed closed, the section should not look like an unexplained empty system.

If causality is provable from runtime facts, show an explanatory empty state such as:

**本轮研究未完成**

`因此今天还没有新的研究结果。`

If current-day research exists from earlier successful cycles, continue showing it normally. A later fail-closed cycle must not hide valid earlier research.

Do not claim all zero-research states are caused by provider/quota failure.

---

# 9. Daily Overview — 今日投资决策

When there is no new current-day InvestmentDecision and the latest cycle is proven fail closed before decision generation, explain:

**本轮未生成新的投资决策**

`研究阶段未完成，因此 Brain 没有进入新的资本配置决策。`

Only show this causal explanation if the runtime proves the cycle stopped upstream of decision generation.

If there are earlier decisions today, show them normally and add the latest-cycle explanation separately rather than replacing history.

Never synthesize an InvestmentDecision from research failure diagnostics.

---

# 10. Daily Overview — 今日动态

Add a factual timeline event for fail-closed cycles when a reliable timestamp exists.

Example:

`10:00 自动投资本轮安全停止`

`研究未完成，因此没有生成新的投资决策或交易指令。`

If a safe confirmed reason exists, it may appear in the detail.

Timeline must use the real cycle timestamp.

Do not invent intermediate event times or order.

Tone: warning, not success.

---

# 11. Technical Details

If useful, expose a collapsed technical-detail area for the latest cycle.

Safe fields may include, when available:

- canonical cycle status (`FAILED_CLOSED`)
- sanitized failure stage
- sanitized failure code/category
- scheduler mode
- next run
- authority count

Do not foreground these on the main user surface.

Do not expose secrets or raw exception text if it may contain sensitive content.

---

# 12. No New Controls

This mission remains observational/read-only.

Do not add:

- retry cycle
- retry LLM
- change provider
- buy / add / hold controls
- force analysis
- force decision
- force execution
- reconcile button
- cancel button
- scheduler pause/resume control
- cadence editor
- RiskPolicy editor
- LIVE switch

If a quota/provider issue requires user action outside DSA, the UI may explain the condition, but this mission does not create a provider-management/control plane.

---

# 13. Preserve Existing Daily Overview Behavior

Do not regress:

- real authoritative connected portfolio rendering
- exact `(market, symbol)` identity
- connected/manual isolation
- `/portfolio?account=connected`
- default connected-account discoverability
- M3-only decision filtering
- HOLD neutral semantics
- BLOCKED/UNKNOWN warning semantics
- original research workbench
- independent source failure isolation
- desktop/mobile layout

---

# 14. Testing Requirements

At minimum cover:

- `FAILED_CLOSED` is recognized explicitly
- healthy scheduler + failed-closed latest cycle still shows scheduler `运行中`
- latest cycle presentation is warning / non-success
- known safe reason maps to expected Chinese user copy
- unknown reason does not invent provider/quota cause
- fail-closed before decision => no synthetic decision/mandate/submission
- current-day earlier research remains visible despite later fail-closed cycle
- current-day earlier decisions remain visible despite later fail-closed cycle
- zero research with proven fail-closed gets explanatory empty state
- zero decision with proven upstream fail-closed gets explanatory empty state
- execution UNKNOWN remains separate from research fail-closed
- pending reconciliation remains separate
- next scheduled run remains visible
- mobile 390px remains readable
- existing Daily Overview regressions remain green
- existing Portfolio / Investment Decisions semantics remain green

If backend/readiness changes:

- add focused API/schema/service tests
- run investment architecture/authority tests
- run M3 scheduler/readiness tests
- run appropriate backend regression/full gate

Always run as applicable:

- focused frontend tests
- full frontend tests
- build
- lint
- Playwright desktop
- Playwright mobile
- `git diff --check`

---

# 15. Realistic Fixtures / Visual Evidence

Add sanitized visual evidence for at least:

- healthy completed cycle
- healthy scheduler + `FAILED_CLOSED` latest cycle with known safe reason
- `FAILED_CLOSED` with unknown exact reason
- earlier research/decision history preserved while latest cycle failed closed
- mobile fail-closed presentation

Fixtures must not encode incorrect M3 authorization semantics.

Do not use LIVE state in visual fixtures.

---

# 16. Autonomous Execution

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine blockers are autonomous, including:

- TypeScript typing
- enum/status mapping
- schema mapping
- test fixture updates
- safe backend observational projection
- UI copy/layout
- Playwright
- build/lint
- stale mocks
- deterministic test failures caused by this change

Codex should diagnose, fix, test, and continue without asking Owner for ordinary implementation choices.

---

# 17. OWNER HARD STOP

Stop only if completion would require:

- changing investment authority
- changing sizing/allocation
- changing RiskPolicy
- changing Athena execution behavior
- enabling SELL / REDUCE
- enabling LIVE / real-money trading
- expanding broker/account permissions
- expanding auth/network exposure
- changing scheduler cadence
- forcing analysis/trades for evidence
- destructive migration/data deletion
- introducing an operator control plane rather than read-only observability

---

# 18. Git Workflow

1. Fetch latest `origin/athena-integration`.
2. Create a new branch/worktree from the exact latest remote base.
3. Implement the smallest coherent change.
4. Commit and push.
5. Open a **Draft PR** targeting `athena-integration`.
6. Record exact base SHA and exact PR head SHA.
7. Include tests, screenshots, authority-boundary statement, and known limitations.
8. Do **not** merge.
9. Do **not** deploy.
10. Stop at **ARCHITECTURE REVIEW GATE**.

---

# Acceptance

The mission is complete when the DSA product can accurately distinguish:

**“系统没在运行”**

from

**“系统正常按周期运行，但最近一轮因为研究未完成而安全停止，因此没有产生新的投资决策或交易指令。”**

And, when the runtime has reliable evidence, it can also explain **why** the research did not complete in concise user-safe Chinese.

The user must be able to understand the latest cycle outcome from the home page without reading logs, while all existing Single Brain fail-closed and simulation-only safety boundaries remain unchanged.

**ARCHITECTURE REVIEW GATE: DSA_RUNTIME_REASON_EXPLAINABILITY_V1_READY**
