# DSA Research Token Budget Attribution v1 — Mission

## Model Mode

- Codex model: **Terra**
- Reasoning: **Medium / 中**
- Escalate to Sol only if a genuine Research/Brain authority or safety-contract ambiguity is discovered.
- This mission is primarily read-only measurement and attribution. Conserve Codex quota.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Mission base: current `athena-integration` governance head.
- Approved M5 application runtime remains `8d538348d4ca9c4633a978f318faf9402119aaab`.
- Current local model remains `Qwen3-14B-MLX-6bit` through the existing loopback oMLX service.
- Current practical model verdict: `LOCAL_QWEN_USABLE_WITH_LIMITATIONS`.
- Current serving evidence: comparable local-Qwen Research requests are roughly 6.6k–7.2k prompt tokens; median model wall time is about 219 seconds; median completion is roughly 1.7k tokens; decode throughput is about 8.8 tokens/sec.
- PR #19's reviewed oMLX assessment found current M5 memory/swap headroom too constrained for meaningful serving-layer A/B without extra risk. That report is evidence for planning only; this Mission does not depend on merging or deploying it.

## Owner Goal

Determine whether **Research token-budget reduction** can materially improve DSA local-Qwen latency before investing engineering effort in a lighter local model.

This mission must answer:

> Where do DSA Research input and output tokens actually come from, which portions are semantically necessary, which portions are duplicated or compressible, and what is the realistic latency/memory upside of slimming them without weakening Research quality or Single Brain safety?

This is **attribution and design only**. Do not change the production prompt or context in this Mission.

## Core Principle

Do not optimize tokens blindly.

DSA Research exists to produce evidence, thesis, scenarios, uncertainty, data-quality assessment, and structured outputs. Token reduction is acceptable only where the same information/contract can be preserved with less representation overhead.

Never remove or weaken:

- required structured-output schema/contract fields;
- decision-action taxonomy needed by downstream Research → Brain semantics;
- risk/uncertainty/data-quality instructions;
- market phase / market structure facts that prevent temporal mistakes;
- source provenance needed for Research integrity;
- instructions that keep account/PortfolioSnapshot/RiskPolicy/execution authority out of Research;
- safety semantics that distinguish Research evidence from Brain capital allocation.

## Phase A — Trace the Exact Production Research Prompt Assembly

Read the exact deployed application source and local runtime configuration. Reconstruct the current Research request assembly path without calling Qwen.

Trace, as applicable:

`pipeline/search-derived intel -> Research context -> Analyzer prompt assembly -> system/base instructions -> market guidelines -> market phase/structure -> technical/fundamental blocks -> news_context -> analysis_context_pack_summary -> output/schema instructions -> LiteLLM/oMLX request`

Identify the exact functions/files that add each prompt section.

At minimum classify prompt components into these semantic buckets when present:

1. base/system role and Research doctrine;
2. market-specific guidelines;
3. decision/action taxonomy and scoring instructions;
4. output schema / JSON contract / examples;
5. market phase context;
6. daily market context;
7. market structure context;
8. technical indicators / price / trend context;
9. fundamental / capital-flow context;
10. connected web/news intelligence context, including Bocha-derived text already persisted;
11. `analysis_context_pack_summary` or equivalent packed context;
12. repeated labels, formatting, explanatory prose, examples, or duplicated facts;
13. any other material block discovered in the exact production path.

Do not infer from stale docs when exact source/runtime evidence is available.

## Phase B — Exact Token Attribution Without New Model Calls

Use existing persisted Research contexts, prompt telemetry, logs, or reconstructable historical inputs. Prefer the **newest 10 comparable completed local-Qwen Research samples** with similar workload shape.

No new Qwen, Bocha, web/search, cloud, paid API, scheduler, or broker call is allowed.

### Tokenizer

Use the tokenizer corresponding to the currently loaded `Qwen3-14B-MLX-6bit` model if locally available. Do not download a different model/tokenizer solely for this mission.

If exact tokenizer access is unavailable, use existing oMLX/request token telemetry and a clearly labelled approximation only for sub-block attribution. Do not present estimates as exact counts.

### Required per-sample accounting

For every selected sample, record sanitized counts only:

- total prompt/input tokens;
- total completion/output tokens;
- each prompt-component token count;
- each component's percentage of prompt tokens;
- repeated/duplicated token count when provable;
- schema/instruction tokens versus factual-context tokens;
- news/intelligence tokens;
- market/technical/fundamental tokens;
- output tokens by top-level structured section where reconstructable without exposing raw content.

Do not place raw prompts, raw news, positions, account balances, API keys, or secrets in the report.

## Phase C — Duplication and Value Analysis

For every material component, classify it as exactly one primary category:

- `MUST_RETAIN_EXACT_SEMANTICS`
- `DEDUPLICATION_CANDIDATE`
- `STRUCTURAL_COMPRESSION_CANDIDATE`
- `BOUNDED_CONTEXT_CANDIDATE`
- `LOW_VALUE_OR_LEGACY_CANDIDATE`
- `UNKNOWN_NEEDS_SEMANTIC_REVIEW`

### Look specifically for

- the same market/price/date facts repeated in multiple prompt sections;
- the same news/intelligence facts repeated between packed context and `news_context`;
- verbose field labels or prose surrounding machine-readable data;
- repeated schema descriptions/examples that are much larger than their semantic value;
- raw historical arrays where a deterministic summary already exists;
- unused or legacy prompt fields that downstream parser/schema no longer require;
- duplicate action/decision instructions across several constants/templates;
- verbose output sections that force high completion-token counts without adding Research value.

Do not label something redundant merely because it is repeated: some repetition may intentionally anchor safety or schema compliance. State the semantic reason before proposing removal.

## Phase D — Latency Impact Model

Use the current observed performance evidence to estimate the **upper bound** and **realistic bound** of token slimming.

Separate:

1. input/prefill savings;
2. output/decode savings;
3. memory/KV/prefill-pressure savings;
4. expected impact on bounded completion/repair frequency.

Do not assume input-token reduction linearly reduces total wall time when decode dominates.

For every proposed slimming package, report:

- estimated input-token reduction;
- estimated output-token reduction, if any;
- expected total token reduction;
- expected latency mechanism;
- conservative and optimistic wall-time savings range;
- quality/safety risk;
- whether it requires a production prompt/schema change later.

### Candidate packages

Design at most 3 **future** packages; do not implement them here.

Prefer:

- **P1: safe dedupe only** — identical/redundant facts, labels, or duplicated packed context;
- **P2: compact representation** — same facts/schema semantics in a more token-efficient representation;
- **P3: bounded Research payload** — only if deterministic evidence shows long raw context can be bounded without losing material Research information.

Any package that changes required output fields, action taxonomy, Research authority, or downstream contracts must be marked `ARCHITECTURE REVIEW REQUIRED` and not recommended for routine implementation.

## Phase E — Decide Whether Solution 1 Can Solve the Latency Problem

Choose exactly one verdict:

### `CONTEXT_OPTIMIZATION_HIGH_VALUE`
Use only if a credible low-risk token package can plausibly reduce end-to-end Research latency by **>=20%** or save **>=60 seconds** on the current comparable workload without weakening structured-output quality.

### `CONTEXT_OPTIMIZATION_SUPPORTING_ONLY`
Use when token slimming should improve prefill/memory pressure and may save meaningful time, but evidence indicates it is unlikely to solve the dominant decode/model-speed bottleneck by itself. This verdict should recommend proceeding to a lightweight-model A/B after harvesting only clearly safe token wins.

### `CONTEXT_ALREADY_NEAR_LEAN`
Use when current prompt/context has little safely removable overhead and expected end-to-end benefit is below 10%.

### `CONTEXT_ATTRIBUTION_BLOCKED`
Use only if exact production request assembly cannot be reconstructed or token attribution cannot be made reliable without prohibited new runtime changes.

## Required Owner Answer

The report must state plainly:

- current median prompt tokens;
- current median completion tokens;
- top 5 token-consuming components;
- estimated provably duplicated/compressible token share;
- safest realistic token-reduction percentage;
- expected Research wall-time savings range;
- whether memory/prefill pressure should materially improve;
- **方案 1 能不能单独解决“慢”：能 / 不能 / 只能部分改善**;
- **是否应该继续进入方案 2（轻量本地模型 A/B）：是 / 否**.

## Safety / Frozen Boundaries

No changes to:

- DSA production `src/`;
- Research prompt/template/schema;
- model identity/quantization/settings;
- oMLX service/config;
- Bocha/search configuration;
- PortfolioSnapshot authority/freshness/skew/hashes;
- RiskPolicy/sizing/Decision Engine;
- scheduler/cadence/topology;
- Athena;
- execution/idempotency/reconciliation/broker permissions;
- LIVE state;
- BUY/ADD/HOLD/SELL/REDUCE capability boundary.

No new model calls. No restart. No deploy. No trading mutation. No secrets.

## Deliverable

Create a dedicated branch from the current canonical `athena-integration` governance head.

Deliver one docs-only report:

`docs/DSA_RESEARCH_TOKEN_BUDGET_ATTRIBUTION_V1_REPORT.md`

The report must contain:

- exact base/head SHA;
- exact production prompt-assembly trace;
- evidence-window selection;
- tokenizer/counting method;
- per-component median token table;
- duplication/compression classification table;
- up to 3 future slimming packages with expected savings/risk;
- exact verdict category;
- required plain-language Owner answer;
- confirmation of zero production/runtime/model/trading mutation.

Open a **Draft PR** to `athena-integration` and stop at:

`ARCHITECTURE REVIEW GATE — RESEARCH_TOKEN_BUDGET_ATTRIBUTION_V1_READY`

No merge. No deployment.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine source tracing, tokenizer discovery, historical prompt reconstruction, log parsing, token counting, deduplication measurement, and report generation are autonomous within the hard limits above.

## OWNER HARD STOP

Stop before continuing if it would require:

- changing the production prompt/schema or Research semantics;
- changing model/quantization/settings;
- changing oMLX config or restarting oMLX/DSA;
- new Qwen/Bocha/cloud/paid calls;
- exposing secrets or raw sensitive account data;
- changing Research/Brain/RiskPolicy authority;
- scheduler/broker/account/trading mutation;
- LIVE or SELL/REDUCE enablement.
