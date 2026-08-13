# DSA Lightweight Local Model A/B v1 — Mission

## Model Mode

- Codex model: **Terra**
- Reasoning: **High / 高**
- Escalate to Sol only if a genuine Research/Brain authority, safety-contract, licensing, or production-isolation ambiguity appears.
- Conserve Codex quota. The work is mostly bounded local evaluation, not architecture redesign.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Governance base: `athena-integration@5e0ee8edb0920d22f3cfc9fe84e7b0c7c6a01351`
- Current approved M5 application runtime remains: `8d538348d4ca9c4633a978f318faf9402119aaab`
- Current production local Research model: `Qwen3-14B-MLX-6bit` through the existing loopback oMLX service.
- Current practical verdict: `LOCAL_QWEN_USABLE_WITH_LIMITATIONS`.
- Current comparable baseline from reviewed evidence:
  - median initial Research input: ~6,986.5 tokens;
  - median completion: ~1,731 tokens;
  - median model/Research wall time: ~211–219 seconds;
  - effective decode throughput: roughly 8–10 tokens/sec;
  - output decode is a material latency component;
  - token/context slimming is `CONTEXT_OPTIMIZATION_SUPPORTING_ONLY`, not a complete fix.
- Serving-layer tuning alone was not shown to provide a safe material win under current M5 memory/swap pressure.

## Owner Goal

Determine whether a **lighter local model or lighter quantization** can materially improve DSA Research latency on the current M5 while preserving enough Research quality, structured-output reliability, and Single Brain safety to replace the current 14B/6-bit local model.

This Mission must answer:

> Is there a lighter local MLX-compatible candidate that is substantially faster than `Qwen3-14B-MLX-6bit` and still good enough for DSA Research?

This is an **offline/local A/B evaluation**. It does not authorize production model replacement or deployment.

## Core Architecture Boundary

Research remains Research.

The model may produce evidence, thesis, scenarios, uncertainty, data-quality assessment, structured actionability, and research price references. It must not receive or control account allocation, PortfolioSnapshot authority, RiskPolicy, target weights, quantities, broker actions, or execution authority.

Brain remains the only capital-allocation authority.

Do not weaken downstream fail-closed validation to make a lighter model look better.

## Candidate Strategy

Evaluate at most **2 lighter candidates** beyond the current baseline.

Candidate discovery must use the exact local oMLX/MLX compatibility surface and trusted model artifacts available at execution time. Do not invent model names or flags from memory.

Prefer candidate classes in this order:

1. **Same-family / same-size lighter quantization** if a trusted MLX artifact exists and materially reduces memory/compute cost while preserving the current model family behavior.
2. **Smaller same-family model**, preferably roughly 7–9B class when available and compatible.
3. A smaller high-quality local instruct model from another family only if the above are unavailable or clearly unsuitable, and only if Chinese instruction following + JSON/structured output + local MLX compatibility are credible.

Avoid very small models merely to win a speed benchmark. A 3–4B class model may be screened only if no better 7–9B candidate is feasible or if it has unusually strong structured-output evidence.

### Candidate trust / licensing

Only use artifacts from official model publishers or established MLX conversion maintainers with clear model identity and license metadata.

Stop at Owner Hard Stop if:

- license or redistribution/use terms are ambiguous for this project;
- the candidate source cannot be trusted;
- candidate requires a paid API or cloud inference;
- candidate requires changing the DSA Research authority model.

### Download budget

Downloading free local model artifacts is allowed for this Mission, bounded to:

- at most **2 candidate model artifacts**;
- no unnecessary duplicate quantizations;
- no paid access;
- no model upload or secret disclosure.

Record model identity, parameter class, quantization, artifact source category, and on-disk size; do not copy license text verbatim into the report beyond what is needed to identify compatibility.

## Frozen Semantics

For A/B comparability, keep unchanged:

- production Research prompt wording;
- output schema / parser / repair policy;
- `enable_thinking=false` semantic;
- generation temperature/top-p/top-k and other production generation settings unless a candidate rejects an unsupported parameter; if unsupported parameters would require behavior-changing recovery, document and reject or stop rather than silently retune;
- Research action taxonomy;
- Research → Brain HOLD semantics;
- PortfolioSnapshot authority/freshness/skew/hash semantics;
- RiskPolicy;
- Decision Engine sizing/target-weight logic;
- scheduler cadence/topology;
- Athena;
- execution/idempotency/reconciliation/broker permissions;
- LIVE state;
- BUY/ADD/HOLD boundary; do not enable SELL/REDUCE.

No prompt shortening in this Mission. The point is to isolate **model/quantization** effect from context optimization.

## Phase A — Candidate Discovery and Resource Feasibility

Before any model load or generation:

1. fingerprint current M5 memory pressure, swap, current oMLX process state, and next scheduled Research window;
2. inspect the installed oMLX/MLX-supported model loading path;
3. identify at most two trusted lighter candidates;
4. estimate candidate memory footprint from artifact/metadata and current runtime evidence;
5. determine the safest isolation strategy.

### Preferred isolation

Prefer a candidate endpoint or direct local inference path that:

- is loopback-only;
- does not modify the production DSA `.env` or source;
- is used only by the non-production evaluation harness/process-local environment;
- cannot accidentally become DSA's production model route.

If current memory headroom safely permits a smaller candidate alongside the loaded 14B model, use an alternate loopback port and preserve API-key protection where oMLX serving is used.

### Controlled sequential fallback

If a concurrent candidate would cause material swap/OOM risk, a **temporary serving-only maintenance window** is allowed only if all are true:

- no active DSA Research cycle;
- the next scheduler run leaves a safe margin for candidate evaluation + rollback;
- DSA itself is not restarted;
- scheduler cadence/config is not changed;
- exact production oMLX service/config/model route is captured first;
- the candidate is exposed only on a non-production loopback endpoint or process-local route;
- production 14B oMLX is restored and health-checked before the next expected scheduler run;
- if a natural DSA cycle begins early or isolation becomes uncertain, abort immediately and restore production oMLX.

Do not let DSA naturally query a candidate during this Mission.

If neither concurrent nor sequential isolation can be made safe, stop with `LIGHTWEIGHT_AB_BLOCKED_BY_RESOURCE_OR_ISOLATION` rather than risking runtime stability.

## Phase B — Historical Baseline

Use existing reviewed production telemetry as the baseline; do not rerun 14B merely for symmetry unless absolutely necessary.

Baseline reference:

- current production model: `Qwen3-14B-MLX-6bit`;
- comparable median wall time ~211–219s;
- median completion ~1,731 tokens;
- effective decode ~8–10 tok/s;
- bounded completion/repair frequency is known to be meaningful;
- recent production results are parseable and operationally usable.

If one fresh baseline replay is needed because the candidate path changes measurement mechanics, it is allowed but counts toward the total full-replay cap below. Prefer not to spend it.

## Phase C — Evaluation Context Set

Use persisted Research-only contexts. No Bocha/search refresh and no synthetic account data.

Select a compact set of **3 semantic context types** when available:

1. **neutral/watch case** — representative of current natural `watch/hold` behavior;
2. **bullish/actionable-candidate case** — a persisted context already identified by technical/research inputs as bullish or previously suitable for actionable-long evaluation; do not fabricate a bullish prompt;
3. **risk/degraded-data or regime-sensitive case** — to test uncertainty/data-quality discipline.

If a true bullish persisted context cannot be found, document that and use the best repository-defined bullish Research fixture/context available without changing prompt semantics.

Do not inject PortfolioSnapshot, balances, positions, RiskPolicy, target weight, quantity, broker state, or execution data into model inputs.

## Phase D — Bounded A/B Run Plan

### Full Analyzer replay cap

Maximum **5 new full local Analyzer replays total** across this Mission.

Recommended allocation:

- Candidate A: 2 contexts;
- Candidate B: 2 contexts;
- best candidate: 1 additional discriminating context.

If only one viable candidate exists, use at most 3 full candidate replays and stop; do not manufacture a second candidate.

A fresh 14B baseline replay, if truly required, consumes one of the five.

No cloud model, paid API, Bocha/search call, scheduler trigger, Brain sizing, mandate, broker, or execution call.

### Harness

Use the existing non-production evaluation harness where practical. Temporary helper code under `tools/` is allowed only if needed to route an evaluation subprocess to a candidate endpoint safely.

Do not change `src/` merely to enable the benchmark.

Suppress evaluation-only persistence writes where the existing harness already does so. Do not create production AnalysisHistory/LLM usage records for candidate comparisons unless an existing read-only evaluation path unavoidably does so; if so, stop and redesign the non-production harness rather than polluting production evidence.

## Phase E — Performance Scorecard

For each candidate and replay, record sanitized evidence:

- exact candidate model identity and quantization;
- model artifact size;
- prompt/input tokens;
- completion/output tokens;
- total Analyzer wall time;
- model response wall time if separable;
- decode tokens/sec if observable;
- TTFT/prefill throughput if observable;
- repair/completion count;
- peak memory pressure and swap delta;
- cold vs warm load status;
- load/startup time separately from steady-state generation.

### Speed requirement

A candidate is worth production consideration only if steady-state comparable Research latency improves materially:

- preferred: **>=35% wall-time reduction**, or
- alternatively: **>=75 seconds saved** on a comparable current multi-minute Research workload,

while passing all quality/stability guards.

A 20–35% improvement may be classified `PROMISING` if quality is clearly strong and memory pressure improves materially.

Below 20% should normally not justify a model swap unless it dramatically improves memory/swap stability or repair frequency.

Do not compare raw wall time without explaining token-count differences.

## Phase F — DSA Research Quality Guard

A faster model is not a winner if it weakens the Research contract.

For every candidate replay, score:

### 1. Transport / structured reliability

- Analyzer `success`;
- parser success;
- schema validation;
- content-integrity result;
- bounded completion/repair count;
- no missing required structured sections after the existing allowed repair path.

### 2. Actionability semantics

- normalized action must be in the existing taxonomy;
- `watch/hold/avoid/alert` must remain safely non-actionable downstream;
- `buy/add`, if produced, must have complete legal long price geometry where required: positive entry/stop/target, `stop < entry`, `target > entry`;
- unsupported `sell/reduce` must not be treated as newly enabled capability;
- ambiguous/unrecognized action is a failure, not something to coerce.

### 3. Factual grounding

Against the persisted input evidence, the candidate must not:

- invent material prices, dates, events, or data availability;
- suppress known risk/data-quality warnings;
- state confidence unsupported by the available context;
- contradict deterministic technical/market facts without an explicit evidence-based explanation.

Do not require exact wording or identical action to the 14B baseline. Semantic differences are acceptable if grounded and contract-valid.

### 4. Research-role discipline

The candidate must not claim account quantity, target allocation, broker action, or execution authority.

### 5. Output usefulness

Assess whether the structured result still gives DSA enough evidence, thesis, scenario/risk framing, uncertainty, and actionable research state for Brain consumption.

## Candidate Rejection Rules

Reject a candidate regardless of speed if any of these repeat materially:

- parser/schema/integrity failure beyond the existing bounded repair policy;
- hallucinated material facts;
- missing risk/uncertainty discipline;
- illegal actionable-long price geometry;
- ambiguous or unsupported action state;
- requirement to enable thinking or materially retune prompt/generation semantics;
- OOM/crash/repeated swap thrash;
- auth/network weakening;
- inability to isolate it from production DSA routing.

One isolated stochastic disagreement is not automatically fatal; repeated structural or safety-relevant weakness is.

## Final Verdict Categories

Choose exactly one:

### `LIGHTWEIGHT_LOCAL_MODEL_RECOMMENDED`
A named candidate materially improves latency and passes DSA quality/stability guards strongly enough to justify a separate production deployment Mission.

### `LIGHTWEIGHT_LOCAL_MODEL_PROMISING_NEEDS_MORE_EVIDENCE`
A candidate is materially faster and mostly good, but the bounded evidence set is insufficient for production replacement.

### `CURRENT_14B_REMAINS_PREFERRED`
Lighter candidates are not good enough, not materially faster, or introduce too much structured/Research quality loss.

### `LIGHTWEIGHT_AB_BLOCKED_BY_RESOURCE_OR_ISOLATION`
Meaningful A/B cannot be completed safely on the current M5 without a separately authorized maintenance/isolation change.

## Required Owner Answer

The report must state plainly:

- which candidate(s) were tested;
- current 14B baseline latency;
- best candidate latency;
- seconds saved and percent improvement;
- candidate decode throughput vs baseline where available;
- memory/swap impact;
- parser/schema/repair comparison;
- whether buy/add structured plan quality was observed and passed;
- the most important quality differences versus current 14B;
- **这个更轻的本地模型能不能替代现在的 Qwen3-14B：能 / 暂时不能 / 不能**;
- **是否建议进入生产模型切换 Mission：是 / 否**;
- if yes, exact candidate model identity/quantization and the minimal route/config change required in a later deployment Mission.

## Safety / Frozen Boundaries

Before closeout confirm:

- M5 DSA application runtime remains the approved SHA unless pre-existing drift is discovered;
- no DSA restart;
- no scheduler cadence/config change or forced scheduler cycle;
- production Prompt/Schema/Research semantics unchanged;
- Athena untouched;
- RiskPolicy/Brain/execution untouched;
- LIVE remains false;
- SELL/REDUCE remains unsupported;
- no broker/account/manual-ledger mutation;
- no cloud/paid model call;
- no Bocha/search refresh for evaluation;
- no secret exposure;
- production oMLX route/model/config restored exactly if any temporary serving maintenance occurred;
- candidate artifacts are not made production-active by this Mission.

## Deliverable

Create a dedicated branch from the current canonical `athena-integration` governance head.

Deliver one report:

`docs/DSA_LIGHTWEIGHT_LOCAL_MODEL_AB_V1_REPORT.md`

Optional non-production helper changes under `tools/` and focused tests are allowed only if needed for safe reproducibility. No production `src/` change is expected.

Open a **Draft PR** to `athena-integration` containing:

- exact base/head SHA;
- candidate selection rationale and trust/license summary;
- resource/isolation method;
- context-set selection method;
- exact replay count;
- performance scorecard;
- quality scorecard;
- memory/swap evidence;
- final verdict;
- plain-language Owner answer;
- proof production route/config was unchanged or restored;
- confirmation of zero DSA/Athena/trading mutation.

Stop at:

`ARCHITECTURE REVIEW GATE — LIGHTWEIGHT_LOCAL_MODEL_AB_V1_READY`

No merge. No deployment. No production model switch.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine candidate discovery, free model download, temporary local helper, tokenizer/model loading, loopback test endpoint, read-only context selection, benchmark parsing, and reversible serving cleanup are autonomous within the hard limits above.

## OWNER HARD STOP

Stop before continuing if it would require:

- paid/cloud inference;
- ambiguous model license or untrusted artifact;
- production Prompt/Schema/Research semantic change;
- changing Research/Brain/RiskPolicy authority;
- DSA restart;
- scheduler cadence/config change;
- allowing production DSA to route to a candidate during the evaluation;
- auth weakening or non-loopback exposure;
- more than 2 candidate model artifacts;
- more than 5 full Analyzer replays;
- destructive cleanup or removal of the current production model;
- broker/account/trading mutation;
- LIVE or SELL/REDUCE enablement;
- secret exposure.