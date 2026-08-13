# DSA oMLX Performance Tuning v1 — Mission

## Model Mode

- Codex model: **Terra**
- Reasoning: **Medium / 中**
- Escalate to Sol only if a genuine safety, auth/network, or Research/Brain authority ambiguity is discovered. Routine performance diagnosis, benchmark design, oMLX CLI/config inspection, and rollback handling stay on Terra.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Governance base: `athena-integration@34a2ed5ab23d515ba57248bf89caf438d71d529b`
- Current approved M5 application runtime remains: `8d538348d4ca9c4633a978f318faf9402119aaab`
- Local Research model remains: `Qwen3-14B-MLX-6bit` via the existing loopback oMLX OpenAI-compatible service.
- Current practical model verdict: `LOCAL_QWEN_USABLE_WITH_LIMITATIONS`.
- The main measured limitation is latency: observed generation spans roughly 187–417 seconds, and bounded completion/repair is frequent.
- PR #18 added `tools/local_qwen_evaluation.py`, a non-production harness that can capture a sanitized Analyzer result without changing production Research behavior.

## Owner Goal

Improve local Qwen serving latency enough to better fit DSA's Research cadence **without changing Research semantics or output quality**.

The question is:

> Can documented, serving-layer oMLX configuration changes materially reduce DSA local-Research latency while keeping the same model, quantization, prompt, parser/schema behavior, and Single Brain safety boundaries?

This mission is **performance tuning of oMLX serving only**. It is not a model-quality rewrite.

## Success Definition

A candidate is worth recommending for production only if all are true:

1. same model identity and quantization: `Qwen3-14B-MLX-6bit`;
2. same DSA prompt / Analyzer / parser / schema / completion behavior;
3. no auth/network weakening;
4. no Research/Brain/RiskPolicy/scheduler/execution semantic change;
5. measured latency improvement is material:
   - preferred: **>=20% reduction** in comparable end-to-end model/Analyzer wall time, or
   - alternatively: at least **60 seconds saved** on the current multi-minute Research workload with corroborating throughput evidence;
6. no structured-output regression in paired replay evidence;
7. no sustained memory-pressure, swap-thrash, crash, or service instability;
8. the original production oMLX configuration is restored at the end of the A/B mission unless a later Owner-authorized deployment mission explicitly applies the winner.

Improvements below 10% should normally be classified as not worth operational complexity. Improvements between 10% and 20% are `MARGINAL` unless they also materially improve TTFT, stability, or repair frequency without new risk.

## Frozen Boundaries

Do **not** change:

- Qwen model family, checkpoint, quantization, or weights;
- DSA prompt or prompt length intentionally for speed;
- sampling/model-generation semantics such as temperature/top-p/top-k solely to alter speed;
- `enable_thinking=false` — keep the current no-thinking production semantic;
- DSA `src/` Research logic, parser, schema, completion/repair policy, or action taxonomy;
- PortfolioSnapshot authority/freshness/skew/hash semantics;
- RiskPolicy, sizing, target weights, Decision Engine authority;
- scheduler cadence/topology;
- Athena;
- broker/execution/idempotency/reconciliation;
- LIVE state;
- BUY/ADD/HOLD capability boundary; do not enable SELL/REDUCE;
- loopback-only network exposure or existing API-key/auth requirement.

No cloud model, paid API, Bocha/search refresh, or external model call is needed for this mission.

## Phase A — Exact Current oMLX Runtime Fingerprint

Read-only first. Record the exact local serving baseline before changing anything.

Inspect the actual installed oMLX runtime and supported configuration surface; do not guess option names from memory.

Record sanitized facts:

- oMLX version/build/installation path;
- exact serving command or service definition, excluding secrets;
- bind host/port and confirmation it remains loopback-only;
- auth enabled state, without exposing key material;
- model path/name and model residency/TTL settings;
- configured concurrency / worker / batching settings;
- supported KV/prefix/hot-cache settings actually present in this installed version;
- memory-guard / cache-memory settings actually present;
- relevant supported engine/prefill/batch knobs actually present;
- current process RSS / unified-memory pressure / swap state before benchmark;
- whether model reloads/unloads occur between DSA calls;
- whether current logs expose prompt tokens, completion tokens, TTFT, prefill throughput, decode throughput, cache hit, or related timings.

Use local `--help`, installed package metadata, local service/config files, and official oMLX documentation only as needed. Do not modify anything in Phase A.

### Phase A output

Produce an exact **baseline configuration fingerprint** and identify only knobs that are both:

- supported by the installed oMLX version; and
- plausibly relevant to a single-stream, long-context DSA Research workload.

Do not tune knobs that only improve multi-user throughput at the cost of single-request latency unless benchmark evidence justifies them.

## Phase B — Baseline Measurement

Use historical evidence first. Do not burn fresh Qwen runs if existing logs already provide a comparable baseline.

Prefer metrics in this order:

1. existing natural DSA/oMLX logs from the current local route;
2. oMLX's installed benchmark facility, if available;
3. at most **one** new baseline Research-only Analyzer replay using an existing persisted context through `tools/local_qwen_evaluation.py` if needed for comparable end-to-end timing.

The baseline should capture, where observable:

- total model response wall time;
- total Analyzer wall time;
- prompt/input token count;
- completion/output token count;
- TTFT;
- prefill tokens/sec;
- decode tokens/sec;
- bounded completion/repair occurrence;
- parser/schema/integrity outcome;
- peak memory pressure / swap delta;
- model reload/cold-start status;
- cache/prefix hit status if exposed.

Do not compare raw wall time across samples with materially different token counts without normalizing or explaining the difference.

## Phase C — Candidate Profile Design

Create at most **3 candidate serving profiles** beyond baseline.

Candidate knobs must come from the **actual installed oMLX supported options**. Likely classes to investigate include, only if supported locally:

- model residency / keep-loaded / TTL behavior;
- single-request concurrency / worker limits;
- continuous batching behavior for a single-stream workload;
- KV/prefix-cache behavior;
- hot-cache size / cache-memory limits;
- documented memory-guard behavior;
- documented prefill/batch/engine serving settings.

Do not invent flags. If the installed oMLX version does not support a knob, exclude it.

### Candidate design rule

Change as few variables as possible per profile. Prefer one-factor-at-a-time first, then one combined winner profile only if individual evidence supports it.

Each candidate must have:

- exact config diff from baseline;
- rationale;
- expected latency mechanism;
- rollback command/config;
- risk notes, especially memory pressure or cache behavior.

## Phase D — Reversible A/B Benchmark

### Preferred isolation

Prefer an isolated ephemeral oMLX test instance on a different **loopback-only** port with equivalent auth, **only if M5 memory headroom makes a second model instance safe**.

Before starting a second instance, inspect unified-memory pressure and expected model footprint. If a second loaded 14B instance would risk swap-thrash/OOM or invalidate the benchmark, do not run it concurrently.

### Controlled single-instance fallback

If safe second-instance isolation is not practical, a temporary serving-only oMLX A/B restart is authorized under this mission **only** with all of these conditions:

- no active DSA Research cycle;
- DSA itself is not restarted;
- no scheduler/trade is forced;
- exact original oMLX config/service definition is captured first;
- bind remains loopback-only and auth remains enabled;
- each candidate is applied temporarily and then rolled back;
- if a natural DSA cycle begins or service health becomes uncertain, abort the candidate and restore baseline immediately;
- no DSA application source/config change.

Do not modify launchd/system service definitions permanently in this mission. Temporary serving args/profile files outside the repo are preferred.

### Benchmark stages

For each candidate:

1. use oMLX's own microbenchmark/benchmark facility first if available;
2. record TTFT/prefill/decode/memory metrics where possible;
3. reject obviously slower or unstable candidates before spending a full Analyzer replay;
4. run a full DSA Research-only replay only for the best candidate(s).

### New local-Qwen call cap

- New full Analyzer replays across this mission: **maximum 3 total**, including any baseline replay.
- Microbenchmarks that invoke local generation should still be kept bounded and documented; do not brute-force a parameter grid.
- No new Bocha/search calls.

Use the same persisted Research-only context for paired baseline/candidate comparison wherever possible. Do not inject PortfolioSnapshot, account, RiskPolicy, quantity, broker, or execution data into the model input.

## Quality Guard

A faster candidate is invalid if it achieves speed by changing model behavior.

For every full Analyzer replay, compare:

- `success`;
- structured action / decision type;
- parser/schema/integrity result;
- bounded completion/repair count if observable;
- presence and internal validity of structured required fields;
- sanitized entry/stop/target if the action is `buy/add`;
- raw-response presence only, not raw content.

Normal stochastic wording differences are acceptable. Structural degradation, new parser failures, missing fields, or increased repair requirement are not.

Do not force exact textual equality.

## Memory / Stability Guard

For each profile record:

- unified-memory pressure before/during/after;
- swap delta if observable;
- model process crash/restart;
- oMLX health after benchmark;
- DSA health remains unchanged;
- whether candidate causes sustained memory pressure after completion.

Any OOM, repeated crash, significant swap-thrash, or degraded service recovery makes the candidate `REJECTED` regardless of speed.

## Recommendation Categories

Choose exactly one final tuning verdict:

### `OMLX_TUNING_RECOMMENDED`
Use when a specific documented serving profile materially improves DSA latency and passes quality/stability guards.

### `OMLX_TUNING_MARGINAL`
Use when improvements exist but are too small or operationally fragile to justify production configuration change now.

### `OMLX_BASELINE_ALREADY_NEAR_OPTIMAL`
Use when tested documented serving knobs produce no material safe improvement.

### `OMLX_TUNING_BLOCKED_BY_RESOURCE_LIMIT`
Use when M5 memory/service isolation makes meaningful A/B impossible without a separately authorized maintenance change.

## Required Final Owner Answer

The report must state plainly:

- baseline comparable latency;
- best candidate comparable latency;
- absolute seconds saved;
- percent improvement;
- TTFT/prefill/decode changes where observable;
- memory/swap impact;
- whether structured-output behavior remained acceptable;
- **是否建议把这个 oMLX 配置正式应用到生产：是 / 否**;
- if yes, exact minimal serving-config diff to apply in a separate deployment mission.

Do not permanently apply the candidate in this Mission.

## Required Safety Verification

Before closeout confirm:

- production DSA runtime still exact approved application SHA unless pre-existing drift is discovered;
- DSA service was not restarted;
- scheduler cadence unchanged;
- Athena untouched;
- RiskPolicy/Brain/execution untouched;
- LIVE unchanged false;
- no SELL/REDUCE enablement;
- no broker/account mutation;
- oMLX bind/auth security unchanged;
- production oMLX serving config restored to exact baseline;
- no secret exposed.

## Deliverable

Create a dedicated branch from the current `athena-integration` governance head.

Deliver one report:

`docs/DSA_OMLX_PERFORMANCE_TUNING_V1_REPORT.md`

Optional non-production benchmark helper under `tools/` is allowed only if needed for reproducibility; no `src/` change is expected.

Open a **Draft PR** to `athena-integration`.

The PR must include:

- exact base/head SHA;
- baseline oMLX version/config fingerprint;
- candidate profile table;
- benchmark method and token-normalization notes;
- latency / throughput / TTFT / memory evidence;
- number of new Analyzer calls;
- exact final tuning verdict;
- recommended production config diff if any;
- proof baseline production oMLX config was restored;
- confirmation of zero DSA/Athena/trading mutation.

Stop at:

`ARCHITECTURE REVIEW GATE — OMLX_PERFORMANCE_TUNING_V1_READY`

No merge. No production oMLX config deployment.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine local benchmark, CLI/version discovery, log parsing, temporary loopback test port, helper script, and reversible profile issues are autonomous within the hard limits above.

## OWNER HARD STOP

Stop before continuing if it would require:

- disabling or weakening oMLX API-key auth;
- binding oMLX beyond loopback;
- changing model/quantization/weights;
- changing DSA prompt or generation semantics;
- changing DSA production `src/` behavior;
- changing Research/Brain/RiskPolicy authority;
- changing scheduler cadence;
- restarting DSA;
- broker/account/trading mutation;
- LIVE or SELL/REDUCE enablement;
- more than 3 full Analyzer replays;
- permanent oMLX production config/service modification;
- secret exposure.
