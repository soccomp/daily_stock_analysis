# DSA Research → Brain HOLD Semantics v1 — Mission

## Model Mode

- Model: **Terra**
- Reasoning: **High / 高**
- Why: the defect is now narrowly localized to the DSA Research → Brain boundary, but the work touches canonical decision semantics and must preserve Single Brain authority. Do not spend Sol quota unless a genuine contract/authority ambiguity remains after local evidence inspection.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Canonical integration branch before this mission: `athena-integration`
- Current deployed application baseline on M5: `f8dcfc6f6ab9f34d141b1f0ccbce3d4b057ea963`
- The integration branch may contain later **docs-only** governance commits. Do not confuse a docs commit with the deployed application SHA.
- Scope: **DSA only**.

## Problem Statement

Two consecutive natural M3 cycles completed Research successfully but failed closed at the same Shadow Wiring price-plan gate:

- `m2-cycle-1aeae68d598706108431f4568543d288bc03660e`
- `m2-cycle-72db7467496f0696eb1347c6612ed3066156beb4`

Both cycles produced a non-actionable / watch-style Research result, while `InvestmentShadowWiringService.build_from_analysis()` unconditionally required an executable long price plan before the deterministic Brain could form a canonical `InvestmentDecision`.

Observed fail-closed reason:

`completed analysis stop is not below the entry limit`

The second cycle included:

- Research action: watch / 观望
- entry limit: `76.86`
- stop: `78.79`
- target: `82.52`
- authoritative Snapshot refresh: RECONCILED and within the approved 1-second clock-skew budget
- no canonical InvestmentDecision
- no mandate / dispatch / broker submission / ExecutionResult

This mission must determine and correct the **Research → Brain interface semantics**, not conceal the issue by changing the model or mutating prices.

## Confirmed Source-Level Concern

At the deployed application baseline:

1. `InvestmentShadowWiringService.build_from_analysis()` calls `_price_plan(result)` before constructing the ResearchBundle / invoking the Brain.
2. `_price_plan()` requires entry + stop + target and rejects `stop >= entry_limit` unconditionally.
3. `DecisionSizingInput` currently requires a positive `proposed_target_weight` and a mandatory `entry_plan`.
4. `InvestmentDecisionEngine` can produce `HOLD`, but only after it has received that trade-shaped sizing input.
5. `InvestmentDecision` currently requires `entry_plan` for every action, including HOLD; stop/target validation is not structurally separated from actionable BUY/ADD semantics.

Therefore a Research result that says “not actionable / watch” can be rejected for lacking a valid executable BUY/ADD plan **before the Brain is allowed to emit canonical HOLD**.

## Architecture Doctrine

Preserve:

> 研究层拥有解释权，决策层拥有资本配置权，执行层拥有操作权但没有投资判断权。

Research may say whether the asset evidence is **actionable or not actionable**. Research must not decide account quantity or capital allocation.

The DSA Brain remains the only authority allowed to convert Research + authoritative PortfolioSnapshot + RiskPolicy into canonical account action and final quantity.

### Required semantic distinction

- Research “watch / 观望 / non-actionable” is **not** itself an account HOLD decision.
- It is an asset-level actionability constraint that prevents BUY/ADD.
- The Brain must still receive the Research evidence plus PortfolioSnapshot and RiskPolicy and produce the canonical account-level `HOLD` with `delta_quantity = 0`.
- No execution mandate may be projected from HOLD.

### Actionable path remains strict

If Research is genuinely actionable for a new/additional long position, the executable plan remains mandatory before BUY/ADD sizing:

- entry must be present and positive
- stop must be present and strictly below entry limit when required by the current policy/contract
- target must be present and strictly above entry limit for the existing long take-profit semantics
- invalid actionable plan must fail closed

**Do not silently downgrade an actionable-but-invalid BUY/ADD candidate to HOLD merely to avoid an error.** The system must preserve the difference between “Research says do not act” and “Research wants to act but supplied an unsafe/malformed plan.”

## Phase A — Evidence and Source-of-Truth Trace

Before modifying source, inspect the current M5/local persisted evidence for the two cycle IDs above and trace the exact structured field(s) that caused the existing UI projection to show `watch` / `观望`.

Trace:

`raw Qwen structured response → AnalysisResult → existing UI DecisionSignal/recommendation projection → Research adapter → Shadow Wiring → Decision Engine`

Confirm:

1. the exact structured, machine-readable source of the Research actionability signal;
2. whether it is stable across the two failed cycles;
3. whether the value is produced directly by the parsed AnalysisResult rather than inferred from localized display prose;
4. whether any existing adapter already normalizes recommendation/action states;
5. whether `watch` has any current account-allocation or execution authority (it must not).

### Ambiguity hard stop

If there is **no reliable structured source** from which to distinguish non-actionable/watch Research from actionable-long Research without guessing from free-form text, STOP before source changes and report an Architecture Blocker with exact evidence and a minimal proposed contract addition.

Do not invent keyword heuristics over prose such as “观望”, “谨慎”, “等待”, etc. unless an existing canonical normalization already owns those semantics.

If the structured source is unambiguous, continue autonomously to Phase B.

## Phase B — Minimal Semantic Repair

Implement the smallest coherent DSA-only change that makes canonical HOLD representable without requiring a fake executable BUY/ADD plan.

The exact internal shape is implementation work, but it must satisfy all invariants below.

### Required invariants

1. **Single Brain preserved**
   - Research only communicates evidence/actionability.
   - Brain produces final `HOLD` / `BUY` / `ADD` and quantity.

2. **Non-actionable Research reaches Brain**
   - A structured non-actionable/watch Research result must not be rejected solely because stop/entry/target do not form an executable long plan.
   - Brain receives authoritative PortfolioSnapshot + RiskPolicy and emits canonical HOLD.

3. **Canonical HOLD**
   - `action = HOLD`
   - `delta_quantity = 0`
   - `target_quantity = current_quantity`
   - no mandate
   - no dispatch
   - no broker submission

4. **No fabricated prices**
   - Do not synthesize/clamp/rewrite entry, stop, or target to satisfy a schema.
   - Do not replace stop with `entry - ε` or similar.
   - Do not use current market price as a fake executable entry solely to make HOLD pass.

5. **Actionable BUY/ADD remains fail-closed**
   - If the structured Research actionability is actionable-long, an invalid/missing execution plan remains a hard fail-closed before any mandate.
   - `stop >= entry` must still fail closed for actionable BUY/ADD.
   - invalid/missing target semantics must remain fail closed where currently required.

6. **No silent downgrade**
   - An actionable Research candidate with a bad price plan must not be converted into HOLD.

7. **RiskPolicy preserved**
   - No changes to risk budgets, max weights, allowed instruments/markets, min cash, concurrency, stop requirements, or sizing formulas beyond the minimum conditional semantics needed to represent a true non-actionable HOLD path.

8. **Execution boundary preserved**
   - DecisionSignal remains a UI/human projection.
   - ExecutionMandate remains the machine projection only for actionable BUY/ADD decisions permitted by existing M3 semantics.
   - HOLD never creates an execution mandate.

## Contract Guidance

Canonical contracts may be changed **only if required** to represent HOLD honestly.

If a contract change is necessary:

- prefer explicit conditional semantics over placeholder values;
- BUY/ADD must retain strict executable-plan requirements;
- HOLD may omit execution-only fields if that is the minimal truthful representation;
- serialization/hash determinism must remain intact;
- existing stored historical decisions must remain readable or have a clearly bounded compatibility path;
- do not introduce account allocation authority into `ResearchBundle`.

Any new Research actionability field must be asset-level and must not encode quantity, target weight, account action, or execution instruction.

## Tests — Minimum Required

Add focused deterministic tests covering at least:

### A. Non-actionable/watch Research

Given:

- successful AnalysisResult
- structured non-actionable/watch actionability
- authoritative RECONCILED simulation PortfolioSnapshot
- effective RiskPolicy
- price references that are absent or are not a valid executable long plan

Prove:

- Research evidence reaches the Brain path
- canonical `InvestmentDecision.action == HOLD`
- `delta_quantity == 0`
- target quantity unchanged
- no mandate / dispatch / broker submission artifact is produced
- no price is fabricated or rewritten

Use one fixture reflecting the observed `stop > entry` shape from the natural-cycle evidence, but do not require live Qwen/Bocha calls.

### B. Actionable long + valid plan

Prove existing BUY/ADD sizing behavior still works with:

- valid entry
- stop < entry
- target > entry
- existing RiskPolicy caps
- exact quantity semantics

### C. Actionable long + invalid plan

Prove:

- `stop >= entry` remains fail-closed
- missing required execution price remains fail-closed
- no conversion to HOLD
- no mandate/submission

### D. HOLD contract semantics

Prove canonical serialization/hash remains deterministic and HOLD validation cannot change quantity.

### E. Authority architecture

Keep / extend architecture tests so Research cannot import broker/worker/execution submission paths and Execution cannot gain research/LLM/Brain sizing authority.

## Regression Scope

Run focused tests first. Expand only to the relevant M2/M3, Shadow Wiring, Decision Engine, decision contract, projection, and architecture suites.

Do not run the full repository gate unless focused/expanded tests reveal a cross-cutting contract compatibility issue.

No benchmark. No local-vs-cloud model comparison. No new Qwen generation is required for this mission.

## Explicit Non-Solutions

Do **not**:

- switch to a cloud LLM
- tune Qwen
- change oMLX
- edit Bocha/search provider configuration
- add prompt instructions merely telling the model “always make stop lower than entry” as the primary fix
- clamp or normalize unsafe prices
- convert malformed actionable BUY/ADD research to HOLD
- bypass RiskPolicy
- permit SELL/REDUCE
- enable LIVE
- change Athena
- change scheduler cadence/topology
- force a scheduler cycle
- force a broker-simulation trade
- add retry loops around trading

## Frozen Boundaries

Unchanged unless explicitly required by the narrow HOLD contract representation described above:

- Athena source/runtime
- authoritative PortfolioSnapshot semantics
- 1-second PortfolioSnapshot skew budget
- 300-second Snapshot freshness
- Research timestamp zero-tolerance
- Snapshot canonical contents/hash
- scheduler: one `M3_SIMULATION_EXECUTION_ONLY`, 3600 seconds
- P1A/P1B OFF
- Qwen model/backend
- Bocha provider configuration
- execution idempotency
- exact quantity
- UNKNOWN reconciliation-before-retry
- no blind resubmit
- partial-fill behavior
- broker permissions
- auth/network exposure
- `LIVE_TRADING=false`
- BUY/ADD/HOLD capability only; no SELL/REDUCE

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine implementation/test blockers are autonomous. Resolve local import/test fixture/type/serialization issues and continue.

Do not ask the Owner to relay routine logs.

## OWNER HARD STOP

Stop if continuing would require:

- LIVE/real-money trading
- SELL/REDUCE capability
- RiskPolicy product choices
- changing investment authority
- changing execution authority
- Athena source or broker permission changes
- auth/network exposure changes
- secret access/exposure
- destructive/irreversible migration
- forced broker/account mutation
- choosing a new cloud LLM/provider or incurring new paid model usage
- guessing an actionability mapping from free-form prose when no reliable structured source exists

## Deliverable / Gate

If Phase A proves a reliable structured actionability source and Phase B is implemented:

1. create a focused branch;
2. commit only the required DSA source/tests/docs changes;
3. open a **Draft PR** to `athena-integration`;
4. include exact base SHA and head SHA;
5. report changed files and the exact semantic mapping used;
6. report focused and expanded test results;
7. explicitly prove both:
   - non-actionable/watch → canonical HOLD → zero execution artifacts
   - actionable invalid price plan → FAIL_CLOSED → zero execution artifacts
8. stop at **ARCHITECTURE REVIEW GATE**.

No merge. No deploy. No runtime restart. No natural-cycle wait.

Final marker:

`ARCHITECTURE REVIEW GATE — RESEARCH_BRAIN_HOLD_SEMANTICS_V1_READY`
