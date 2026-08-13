# DSA Local Qwen Actionable Research Quality v1 — Mission

## Model Mode

- Codex model: **Terra**
- Reasoning: **Medium / 中**
- Escalate only if the investigation uncovers a genuine Research/Brain authority or contract ambiguity. Do not spend Sol quota for routine evidence collection.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Governance base: `athena-integration@c0ab6480a57b9b8e84cf88f19296c9bff2685b86`
- Current approved M5 application runtime: `8d538348d4ca9c4633a978f318faf9402119aaab`
- PR #16 Research → Brain HOLD semantics is closed by natural-cycle evidence: structured `watch` reached canonical Brain `HOLD` with zero execution artifacts.
- Current local text model route: `openai/Qwen3-14B-MLX-6bit` via the existing loopback oMLX service.

## Goal

Determine whether the **current local Qwen Research model** is good enough for the present DSA Research path before the Owner spends money on a cloud LLM.

This mission evaluates **model-output quality**, not Research → Brain interface semantics. PR #16 already removed the universal executable-price-plan bug from non-actionable Research.

The specific question is now:

> When Research is genuinely structured as `buy` / `add`, does the current local Qwen route reliably produce a parseable, schema-valid, internally coherent actionable-long Research result with a valid long price plan?

Do not enable or purchase a cloud model in this mission.

## Scope

**Evaluation only. No application source change is expected.**

Allowed:

- read-only inspection of persisted DSA Research/LLM evidence;
- at most two bounded **offline local-Qwen Analyzer replays** if historical evidence is insufficient;
- temporary non-git helper scripts/files outside the repository if needed;
- a docs-only evaluation report committed on a dedicated branch and opened as a Draft PR for review.

Not allowed:

- DSA source behavior changes;
- prompt tuning;
- model parameter tuning;
- cloud LLM calls or paid API use;
- Bocha/search calls solely for this evaluation;
- Athena, PortfolioSnapshot, RiskPolicy, scheduler, execution, broker, auth, or network changes;
- deployment or runtime restart;
- forced scheduler cycles or trades.

## Key Invariant

Do not confuse model quality with downstream architecture.

If a sample fails because of a parser/adapter/interface defect independent of the model output, classify it as an **architecture/software defect**, not a Qwen quality failure, and stop before recommending a cloud purchase on that basis.

## Phase A — Historical Evidence First

Use read-only persistence/runtime evidence to inspect completed analyses produced by the current local Qwen route.

Prefer the smallest sufficient scan. Inspect no more than the most recent **30 completed local-Qwen Research analyses** unless a narrower set already proves the result.

Identify every sample whose normalized structured `AnalysisResult.action` is `buy` or `add`.

For each actionable-long sample, record sanitized evidence only:

- cycle/report identifier;
- model identity;
- structured `action` and `decision_type`;
- generation latency if persisted;
- whether the first response parsed successfully;
- bounded completion/repair count, if any;
- parser/schema/content-integrity result;
- sanitized numeric `entry`, `stop`, `target` references actually consumed by the Research → Brain adapter;
- whether `0 < stop < entry <= target` is true, with the stricter existing executable rule `target > entry` reported explicitly;
- whether Shadow Wiring/Brain accepted the Research plan or the exact downstream reason it did not;
- whether any failure occurred before execution authority.

Do not include raw prompts, API keys, account balances, positions, PortfolioSnapshot payloads, or secrets in the report.

### Phase A stop rule

If Phase A yields at least **two independent actionable-long local-Qwen samples**, do **not** make new Qwen calls. Proceed directly to scoring and report.

## Phase B — Bounded Offline Replay Only If Needed

Run Phase B only if Phase A yields fewer than two actionable-long samples.

### Replay source selection

Reuse existing persisted **Research-only** inputs/context. Prefer, in order:

1. the most recent persisted contexts that previously produced structured `buy` / `add` Research under any existing recorded run; or
2. existing persisted contexts that the repository already classifies as bullish/actionable candidates before account allocation.

Do not invent a synthetic bullish prompt merely to force `buy` or `add`.

If no suitable persisted Research-only replay input exists, stop as `INSUFFICIENT_ACTIONABLE_EVIDENCE`.

### Replay limits

- Maximum: **2 new local Qwen Analyzer replays total**.
- Use the current production Analyzer path and current local model route.
- No Bocha/web/search refresh; reuse persisted context.
- No PortfolioSnapshot, account state, RiskPolicy, target weight, quantity, broker, or execution data may enter the LLM input.
- Do not call Brain sizing, mandate projection, broker submission, or scheduler execution as part of the replay.
- Allow only the Analyzer's existing single bounded completion/repair behavior; do not add retries.
- Do not tune prompt/model settings between samples.

For each replay, collect the same sanitized fields as Phase A.

If both replay outputs remain non-actionable, report the factual result; do not manipulate the prompt to obtain a BUY/ADD sample.

## Quality Scoring

Score only samples whose final normalized structured action is `buy` or `add`.

An actionable sample is **PASS** only if all are true:

1. a valid `AnalysisResult` is produced by the existing parser/schema path;
2. required content-integrity checks pass after at most the existing one bounded completion/repair;
3. structured action is unambiguous and in `buy/add`;
4. executable long plan fields required by current DSA semantics are present;
5. numeric plan satisfies `entry > 0`, `stop > 0`, `target > 0`, `stop < entry`, and `target > entry`;
6. no price is placeholder-only, fabricated by downstream code, or silently clamped/reordered;
7. the sample can reach the current Research → Brain actionable-plan gate without failing for a model-produced structural/price inconsistency.

Track separately, but do not automatically fail the sample solely for:

- long latency;
- one normal bounded completion/repair;
- a later PortfolioSnapshot/RiskPolicy/market-state decision that is independent of Research output quality.

## Verdict Categories

Choose exactly one:

### `LOCAL_SUFFICIENT_FOR_CURRENT_RESEARCH_PATH`

Use only if there are at least **2 independent actionable-long samples** and all evaluated actionable samples PASS the structural/price-plan criteria, with no repeated parser/schema/integrity defect.

### `LOCAL_OUTPUT_QUALITY_MIXED`

Use if there are at least 2 actionable samples and results are mixed: one or more PASS and one or more model-output structural/price-plan failures.

### `LOCAL_STRUCTURED_OUTPUT_WEAKNESS_CONFIRMED`

Use only when repeated independent actionable-long samples show the same material model-output weakness, such as invalid/missing executable prices, repeated schema/integrity failure, or repeated repair that still cannot form a valid actionable result.

### `INSUFFICIENT_ACTIONABLE_EVIDENCE`

Use if, after Phase A and the allowed bounded Phase B, fewer than 2 actionable-long local-Qwen samples exist.

Do not label the model weak merely because it often concludes `watch/hold/avoid/alert`.

## Cloud-Model Decision Guidance

The report must include one of these recommendations, without enabling anything:

- `NO_PAID_CLOUD_TRIAL_NEEDED_YET`
- `PAID_CLOUD_A_B_TRIAL_JUSTIFIED`
- `DEFER_DECISION_MORE_NATURAL_EVIDENCE_NEEDED`

A paid cloud A/B trial is justified only if this mission isolates repeated **model-output** weakness after the PR #16 architecture repair. A cloud model must not be recommended to mask a software/interface defect.

## Safety / Governance Checks

Confirm throughout:

- runtime remains exact approved app SHA unless pre-existing factual drift is discovered;
- no restart/deploy;
- one existing `M3_SIMULATION_EXECUTION_ONLY` scheduler at 3600 seconds remains untouched;
- P1A/P1B remain untouched;
- `LIVE_TRADING=false` remains untouched;
- no SELL/REDUCE capability change;
- no broker/account mutation;
- no new paid API usage;
- no secret exposure.

## Deliverable

Create a dedicated branch from the canonical governance base and add **one docs-only report**:

`docs/DSA_LOCAL_QWEN_ACTIONABLE_RESEARCH_QUALITY_V1_REPORT.md`

The report must contain:

- exact evidence window and sample-selection method;
- Phase A sample count and actionable-long count;
- whether Phase B was needed and exact number of new local Qwen calls (0–2);
- per-actionable-sample sanitized scoring table;
- repeated failure pattern, if any;
- final verdict category;
- cloud-model recommendation category;
- explicit statement that no trading/runtime/config/source mutation occurred.

Open a **Draft PR** to `athena-integration` containing only the report. Include exact base/head SHA and stop at:

`ARCHITECTURE REVIEW GATE — LOCAL_QWEN_ACTIONABLE_RESEARCH_QUALITY_V1_READY`

No merge. No deployment.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine read-only query, fixture selection, temporary helper, parsing, and report-generation blockers are autonomous. Resolve them and continue within the hard limits above.

## OWNER HARD STOP

Stop and report if continuing would require:

- paying for or enabling a cloud model/provider;
- exposing secrets;
- changing prompt/model/runtime configuration;
- modifying DSA application source;
- changing Research/Brain/investment authority semantics;
- changing RiskPolicy;
- forcing scheduler/broker/account mutation;
- enabling LIVE or SELL/REDUCE;
- more than 2 new local Qwen Analyzer calls.
