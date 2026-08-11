# DSA Local oMLX Qwen3 Integration v1 — Codex Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a cross-surface local-runtime integration and acceptance task across DSA LiteLLM routing, oMLX service configuration, Analyzer structured generation, runtime restart/alignment, and Single Brain safety boundaries; it does not require a full cross-repo architecture redesign.

---

# Mission Name

**将 M5 本地 oMLX / Qwen3-14B-MLX-6bit 接入 DSA 作为唯一有效文本生成后端，并完成本地模型能力验收与安全优化**

## Canonical Source

Repository: `soccomp/daily_stock_analysis`

Target branch: `athena-integration`

Exact source base at mission authoring:

`15b0b29493d1bbe5a7b302c3a1cf8bd2e83ba693`

The currently deployed DSA application baseline before this mission is the PR #12 merge application commit:

`2ded7a711098667c3fd462d86d1f52b632a4923d`

The branch is ahead only by deployment-governance documentation. Start from latest `origin/athena-integration`, record the exact base, and distinguish tracked source changes from M5-only runtime configuration changes.

---

# Owner-provided runtime facts to verify, not blindly assume

The Owner reports that on the M5:

- oMLX is already installed and running.
- OpenAI-compatible API is intended to be loopback-only at `127.0.0.1:8000`.
- `/v1/models` currently returns one model: `Qwen3-14B-MLX-6bit`.
- A direct chat-completions request has already loaded the model and produced a coherent response.
- oMLX is API-key protected.
- Existing cloud LLM routes previously used by DSA, including Alibaba/Qwen cloud access, are no longer usable.

**Verify all of these on the real M5 before changing DSA.**

The Owner supplied the oMLX API credential out-of-band. **Never write that credential into this repository, a GitHub comment/PR, test artifact, screenshot, command transcript, shell history excerpt, diagnostic preview, or closeout.** Prefer recovering/reusing the credential from the already-running local oMLX service configuration on M5 without echoing its value. If the credential cannot be recovered or reused locally without exposing it, stop only that credential-dependent step and report the blocker; do not invent a key or disable oMLX authentication.

---

# Goal

Make the local oMLX-hosted `Qwen3-14B-MLX-6bit` the **only active DSA text-generation route** on M5 and prove that it can safely support the DSA backend's real LLM-dependent generation workload.

Success means:

1. DSA's effective generation backend is `litellm`, routed only to the loopback oMLX OpenAI-compatible endpoint.
2. Dead cloud routes are not in the effective model routing/fallback path and cannot create slow failover storms or consume cloud quota.
3. DSA can successfully perform its own generation-backend JSON smoke through the real oMLX model.
4. Representative DSA Analyzer/report generation can produce valid Chinese structured output that passes the existing DSA parser/schema/integrity path.
5. Market-review / ordinary `generate_text()`-style generation remains functional where it shares the generation backend.
6. If currently enabled Agent/LiteLLM tool-calling paths depend on the main model, their real compatibility is tested separately and reported truthfully; text-generation success must not be misreported as Agent tool-calling success.
7. oMLX is tuned conservatively for this 32GB host, prioritizing DSA reliability, structured output, host headroom, and deterministic failure behavior over maximum benchmark throughput.
8. No investment authority, RiskPolicy, trading capability, broker state, scheduler cadence, Athena deployment, auth exposure, or network exposure is expanded.

---

# Architecture / authority rules

Single Brain doctrine remains unchanged:

- Research layer may produce evidence, thesis, scenarios, uncertainty and structured AnalysisResult / ResearchBundle inputs.
- DSA Brain remains the capital-allocation authority.
- Athena remains execution/safety/broker infrastructure.
- The local LLM must **not** receive new authority to size positions, submit orders, retry broker actions, alter RiskPolicy, or bypass deterministic decision/execution gates.

This mission changes **model transport/configuration and observability only** unless an unexpected source compatibility defect is discovered.

No LIVE trading. No SELL/REDUCE capability addition. No forced trade. No scheduler cadence change. No Athena source/deployment change.

---

# Existing DSA integration path to prefer

The repository already supports OpenAI-compatible custom channels through the current LiteLLM channel configuration. Prefer using the existing path rather than inventing a new provider implementation.

Expected shape, subject to verification against the current parser and real `/v1/models` response:

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=

LLM_CHANNELS=omlx
LLM_OMLX_PROTOCOL=openai
LLM_OMLX_API_SURFACE=chat_completions
LLM_OMLX_BASE_URL=http://127.0.0.1:8000/v1
LLM_OMLX_API_KEY=<LOCAL SECRET; NEVER COMMIT OR PRINT>
LLM_OMLX_MODELS=<EXACT ACTIVE OMLX MODEL OR DSA PROFILE ID>
LITELLM_MODEL=openai/<EXACT ACTIVE OMLX MODEL OR DSA PROFILE ID>
```

Do not blindly paste this block. Verify the current config parser, existing M5 `.env`, Web/system-config persistence behavior, and effective LiteLLM model list first.

`GENERATION_FALLBACK_BACKEND=` is preferred when the local LiteLLM path is the only valid backend so an unavailable oMLX service fails clearly instead of bouncing to obsolete cloud backends. If current runtime semantics require an explicit self-no-op instead, use the repository-supported equivalent and prove the effective behavior.

If `AGENT_LITELLM_MODEL` is explicitly set to a dead cloud model, inspect current Agent usage and capability before changing it. A local text-generation route is not automatically proof of reliable tool calling. If Agent mode is currently enabled, test the local Qwen route with a harmless read-only tool call before claiming Agent support. If tool calling is unreliable, keep the behavior fail-closed and disclose the limitation; do not fabricate tool success or enable new Agent capability.

Do not route vision/image features to this text-only Qwen model unless the actual model endpoint advertises and passes the existing DSA vision contract. Vision is not a required acceptance item for this mission.

---

# Phase 0 — Preflight, provenance, backups

Before any mutation:

1. Record exact GitHub base and current M5 DSA source/runtime SHA.
2. Record DSA launchd state for `com.dsa.webui`, runtime command, loopback binding, and PID.
3. Record current Single Brain readiness: M3 scheduler mode, authority count, cadence, execution authorization, pending execution count, LIVE false/simulation-only facts.
4. Back up the M5 DSA `.env` and any runtime config file that this mission may edit. Preserve permissions; do not print secret values.
5. Inspect oMLX installation method and exact version: macOS app, Homebrew service, manual process, or other.
6. Record oMLX process/service PID, bind address/port, model directory, settings location, and current memory/concurrency/profile settings in sanitized form.
7. Back up `~/.omlx/settings.json` or the actual equivalent settings source if present, plus any service plist/config that will be changed. Never include the API key in evidence.
8. Record pre-change host memory pressure and oMLX resident/process memory after the model is loaded.

A reversible config backup is mandatory before editing either DSA or oMLX runtime configuration.

---

# Phase 1 — Verify oMLX as a real local dependency

Use loopback only.

Required checks:

1. Confirm the oMLX listener is bound only to loopback. If it is exposed on `0.0.0.0`, LAN, Tailscale, or another interface, **OWNER HARD STOP** before expanding or normalizing that exposure. Do not change network exposure under this mission without Owner approval.
2. Confirm API authentication is enforced. Do not disable it for convenience.
3. Authenticated `GET /v1/models` must succeed and report the expected base model or the later DSA profile.
4. Run one short authenticated `POST /v1/chat/completions` and verify non-empty final `content`.
5. Inspect whether oMLX returns `reasoning_content`, `<think>...</think>`, or other reasoning metadata separately from final content. DSA must consume the final answer, not a reasoning-only envelope.
6. Run a strict JSON generation probe. Require syntactically valid JSON in final content without relying on a human cleaning it up.
7. Record latency, generation throughput if exposed, and process-memory peak in sanitized form.

Do not use this phase to change DSA yet.

---

# Phase 2 — Conservative oMLX optimization for DSA on 32GB M5

The goal is not maximum tokens/sec. The goal is reliable hourly/background structured generation without starving macOS or producing malformed reports.

## 2.1 Detect actual supported controls

Use the installed oMLX version's real CLI/admin/settings schema. Do not copy flags from a newer upstream README if the installed version does not support them.

Current upstream oMLX supports model profiles, chat-template kwargs, process/model memory guards, TTL/LRU behavior, cache controls and request concurrency. Use only capabilities verified on this installed version.

## 2.2 Prefer a dedicated DSA profile when supported

If the installed oMLX version supports model profiles and Qwen3 chat-template kwargs:

- Keep the base `Qwen3-14B-MLX-6bit` model available for manual chat.
- Create a DSA-specific profile exposed through `/v1/models`, preferably a clear ID such as `Qwen3-14B-MLX-6bit:dsa`.
- Prefer `enable_thinking=false` for the DSA profile after verifying the model/template supports it. DSA's routine Analyzer path needs concise, stable structured final output more than long chain-of-thought.
- Do not expose or persist hidden reasoning in DSA reports.
- Do not create a second physical model copy; the profile should reuse the same loaded engine where oMLX supports per-request profile overlays.

If profiles or `enable_thinking=false` are unavailable on the installed version, do not patch oMLX or DSA just to emulate them in this phase. Test the base model as-is and report the limitation. A source change to inject `/no_think` or alter prompt contracts requires the source-change gate below.

## 2.3 Sampling

Do not override DSA's existing generation parameters merely to match a benchmark recipe. First inspect what DSA actually sends.

For Qwen3 non-thinking mode, upstream guidance commonly uses moderate sampling rather than greedy decoding. If the current DSA defaults already produce stable JSON, preserve them. Only tune temperature/top-p/top-k/min-p if repeated structured-output tests show a concrete problem, and document before/after evidence.

## 2.4 Memory guard

On a 32GB host, preserve meaningful headroom for macOS, DSA, Python, browser/UI, Athena tunnel/runtime support, and filesystem cache.

- Verify oMLX process memory guard is enabled.
- Do not configure oMLX to consume the full 32GB.
- The current upstream default concept of roughly `RAM - 8GB` is a reasonable upper safety reference, but use actual M5 memory pressure and the installed version's guard semantics rather than blindly hardcoding 24GB.
- Set any model/process cap only after observing the loaded Qwen model's real peak plus KV/cache overhead.
- Acceptance requires no memory-pressure/OOM event during the sequential DSA replay test.

## 2.5 Concurrency

DSA reliability is the priority. Start with effective generation concurrency = **1** unless the real DSA configuration already requires otherwise.

- Keep `GENERATION_BACKEND_MAX_CONCURRENCY=1` for the first acceptance run.
- oMLX max concurrent requests should not be raised merely because upstream defaults allow more.
- Only raise to 2 if a controlled benchmark proves stable memory and materially improves a real DSA workload. Do not exceed 2 in this mission.

## 2.6 Context limit

Do not assume the model's maximum context should be used.

- Measure token length or the best available prompt-size approximation for representative real DSA Analyzer prompts.
- Choose the smallest safe context ceiling that covers the observed workload with headroom.
- Prefer a practical 8K–16K range if the real prompts fit, but never silently truncate a real DSA prompt to hit this target.
- If representative prompts need more, increase conservatively and record memory impact.

## 2.7 TTL / keep-loaded behavior

There is one local model and DSA's autonomous cadence is hourly.

- Measure cold-load cost and loaded idle memory.
- If host memory pressure remains healthy, keeping the model loaded or using a TTL long enough to bridge normal DSA usage may improve reliability/latency.
- If the host experiences meaningful pressure, allow LRU/TTL unload and accept cold-start latency.
- Do not pin the model at the cost of host stability.

## 2.8 Cache and experimental acceleration

Do not enable experimental speculative-prefill/TurboQuant/draft-model features in v1 unless they are already enabled and proven stable with this exact model.

SSD KV cache is not automatically useful for largely stateless stock-analysis prompts. Leave it unchanged unless measurement proves a benefit without excessive complexity or disk churn.

---

# Phase 3 — Make oMLX the only active DSA text-generation route

Inspect the current M5 effective LLM configuration before editing.

The Owner reports old cloud providers are invalid. Do not delete unrelated secrets or unrelated provider configuration blindly, but ensure they are **not part of the active DSA model route**.

Preferred effective behavior:

- `GENERATION_BACKEND=litellm`
- one explicit `LLM_CHANNELS` entry for oMLX only
- OpenAI-compatible chat-completions surface
- loopback base URL `http://127.0.0.1:8000/v1`
- exact model ID returned by oMLX, preferably the verified `:dsa` non-thinking profile if created
- local API key stored only in M5 protected runtime config
- model-level routing contains no obsolete DashScope/Alibaba/AIHubMix/OpenAI/other dead deployment
- backend fallback does not point to a dead backend

After editing:

1. Run DSA config validation before restart if possible.
2. Inspect effective model list and provider route without printing API key.
3. Restart only the DSA service(s) required to load configuration.
4. Do not restart Athena.
5. Reconfirm DSA loopback `127.0.0.1:8080` and launchd health.
6. Reconfirm Single Brain scheduler authority and 3600-second cadence unchanged.

A normal DSA restart may cause an already-due scheduler cycle to run according to existing accepted restart semantics. Do not manually trigger or accelerate a production M3 cycle for this mission. Do not force a BUY/ADD. If a natural cycle occurs, observe it only.

---

# Phase 4 — DSA-native LLM capability validation

Connection success alone is not enough.

## 4.1 Configuration validation

Require:

- no DSA structured config error for the effective LLM route
- effective generation model resolves to the local oMLX model/profile
- obsolete cloud routes are absent from effective routing
- logs/provider trace show local loopback transport, not failed cloud attempts

## 4.2 Existing DSA generation-backend JSON smoke

Use the repository's existing explicit generation-backend smoke endpoint/service (the same contract used by Web system settings) against the real local model.

Acceptance:

- request reaches oMLX on loopback
- final content is non-empty
- required JSON contract parses successfully
- no secret is exposed in diagnostics
- no backend fallback/cloud call occurs

## 4.3 Analyzer/report qualification

Run at least **3 representative DSA Analyzer prompt replays** using the real production prompt-building/parsing/integrity code but **without broker execution and without forcing the autonomous scheduler**.

Prefer already-saved/sanitized historical analysis inputs or deterministic representative fixtures that exercise:

1. ordinary technical + news synthesis
2. conflicting evidence (e.g. technical vs. fundamental/news)
3. missing/degraded data where the model must acknowledge limitations instead of inventing facts

For each replay record:

- prompt/context size
- wall time
- output token count if available
- peak oMLX process memory if observable
- whether final content contained reasoning wrappers
- raw JSON syntax success
- DSA repair usage, if any
- `AnalysisReportSchema` / existing parser success
- integrity retry count
- placeholder/fallback usage
- Chinese-language quality and obvious contradictions

Do not use the model's prose fluency as the acceptance criterion. The important criterion is whether **DSA's existing structured report contract accepts the result without semantic corruption**.

At least 2/3 should succeed on the first normal DSA generation attempt. All accepted final reports must pass the existing parser/integrity path. Any repeated schema failure is a real limitation, not something to hide by endless retries.

## 4.4 Sequential stability

Run a bounded local soak consisting of:

- at least 10 short JSON generation-backend smoke requests sequentially, and
- the 3 full Analyzer replays above.

Concurrency remains 1 for this soak.

Acceptance:

- no oMLX crash/restart
- no process OOM/memory-guard abort
- no empty final content
- no reasoning-only response treated as success
- no cloud fallback
- no DSA secret leakage

## 4.5 Ordinary generation / market-review dependency

Run one representative non-trading DSA ordinary generation path that shares the generation backend, such as market-review/generate-text behavior, using the narrowest safe test harness available.

Do not initiate a full scheduled trading cycle solely to prove this path.

## 4.6 Agent/tool-calling capability — separate result

If current DSA Agent mode or other tool-calling features are enabled and depend on LiteLLM:

- run one harmless read-only tool-call smoke through the real local model
- verify the model emits a valid tool call and the existing DSA tool surface handles it
- do not enable Agent mode just for this test if it was previously disabled

Report one of:

- `AGENT TOOL CALLING PASS`
- `AGENT TOOL CALLING NOT IN USE`
- `AGENT TOOL CALLING LIMITATION`

Do not block core Analyzer integration solely because optional Agent tool calling is unsupported, unless the current production configuration actually depends on it.

---

# Phase 5 — Safety regression after DSA restart/config change

Reconfirm all of the following:

- Athena remains READY and simulation-only.
- `LIVE_TRADING=false`.
- DSA execution mode remains `SIMULATION_EXECUTION`.
- simulation authorization remains the previously accepted state.
- exactly one M3 scheduler authority.
- cadence remains exactly 3600 seconds.
- P1A/P1B remain OFF.
- pending execution count is not increased by this mission's test harness.
- connected Athena portfolio remains read-only and is not merged into the manual ledger.
- no RiskPolicy, PortfolioSnapshot contract, decision sizing, mandate, execution, broker, auth, network, SELL/REDUCE, or trading-permission code/config change occurred.

If a natural scheduler cycle runs during the maintenance window, record the factual result. Do not retry or force it.

---

# Source-change gate

The expected implementation is **configuration-only** because DSA already supports OpenAI-compatible custom LiteLLM channels.

If the real local model reveals a DSA source-code compatibility defect — for example:

- oMLX final `content`/`reasoning_content` handling is incompatible with the current parser,
- an OpenAI-compatible channel cannot represent the model/profile correctly,
- Qwen JSON output requires a safe generic parser fix,
- config validation incorrectly rejects the loopback provider,
- local usage telemetry handling corrupts runtime semantics,

then:

**ARCHITECTURE REVIEW GATE**

1. Create a new branch from latest `origin/athena-integration`.
2. Make the smallest generic fix; do not special-case the Owner's API key or machine path.
3. Add focused regression tests.
4. Push a **Draft PR**.
5. Do not merge it.
6. Do not deploy source code from that PR.
7. Stop at Architecture Review Gate and post the exact HEAD/tests/limitation.

Routine M5 `.env`, launchd restart, oMLX profile/settings, loopback smoke, diagnostics, backups and rollback work are autonomous within this mission.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine blockers are not hard stops. Diagnose, fix, test and continue when the fix is reversible and remains inside this mission, including:

- stale DSA local LLM env values
- obsolete active cloud model names
- oMLX service not started
- local port not yet released after restart
- local model cold-load delay
- supported oMLX profile/settings adjustments
- DSA config validation errors caused by local channel syntax
- local timeout/output-limit tuning within existing safe bounds
- test harness issues
- sanitized logging/evidence issues

Do not ask the Owner to relay routine command output.

---

# OWNER HARD STOP

Stop and ask for Owner authorization before:

- exposing oMLX or DSA beyond loopback
- disabling oMLX API authentication
- changing/rotating the API key because the existing local credential cannot be reused
- enabling LIVE trading
- enabling SELL/REDUCE
- changing RiskPolicy or investment authority
- changing Single Brain cadence
- changing Athena deployment/source
- destructive database migration
- destructive model/runtime deletion
- installing an unverified experimental oMLX build or patching oMLX source
- making a source PR merge/deploy decision

---

# Acceptance matrix

## Required — core local generation

- oMLX service verified on loopback with authentication.
- exact oMLX version and install mode recorded.
- exact active model/profile recorded; no secret recorded.
- DSA effective model route contains only the local oMLX deployment for normal text generation.
- DSA generation-backend JSON smoke PASS.
- 3 representative Analyzer replays completed with accepted structured outputs; at least 2 first-attempt successes and all accepted outputs pass the normal DSA parser/integrity path.
- 10 sequential JSON smokes complete without oMLX crash/OOM/empty-content/reasoning-only false success.
- one ordinary non-trading generation path PASS.
- no cloud LLM request/fallback observed.
- DSA/Athena trading safety state unchanged.

## Required — oMLX tuning evidence

Record sanitized before/after values for:

- process/model memory policy
- observed loaded/peak memory
- max concurrency
- context ceiling/profile context behavior
- thinking/profile behavior
- TTL/keep-loaded behavior
- any cache setting changed

Every changed value must have a reason tied to observed DSA behavior.

## Optional/conditional

- Agent tool-calling PASS if current production configuration uses it; otherwise report not in use or limitation.

---

# Rollback

Prepare and prove a rollback plan before declaring PASS:

1. Preserve pre-mission DSA `.env` backup with secure permissions.
2. Preserve pre-mission oMLX settings/service-config backup.
3. Record pre/post service commands and PIDs without secrets.
4. Rollback must be able to restore the previous DSA model configuration and oMLX settings independently.
5. Do not roll back to dead cloud providers as a claimed healthy state; rollback means restore the prior local machine configuration, not pretend obsolete provider credentials work.

---

# Canonical closeout

Repository Issues are disabled, so use the **merged DSA PR #12 conversation thread** as the temporary canonical operations evidence location for this config-only integration, unless this mission creates a new source Draft PR under the source-change gate.

Post one sanitized closeout comment titled:

`M5 local oMLX/Qwen3 integration closeout — v1`

Include:

- status: `INTEGRATION PASS`, `PASS WITH LIMITATION`, or `SOURCE FIX REQUIRED`
- exact GitHub base and M5 running source SHA
- oMLX version/install mode and loopback/auth status
- exact model/profile ID
- sanitized effective DSA LLM route (no key)
- confirmation that obsolete cloud routes are absent from effective routing
- direct oMLX smoke result
- DSA JSON smoke result
- Analyzer replay matrix with 3 cases and parser/integrity outcomes
- sequential soak result
- ordinary generation result
- Agent tool-calling status if applicable
- before/after oMLX tuning summary and memory/latency observations
- DSA launchd/runtime state
- Single Brain/Athena safety facts
- warnings/limitations
- rollback refs/backup locations in sanitized form

Never include the oMLX API key, balances, account identifiers, full holdings, raw private prompts/news payloads, or secret-bearing logs.

Do not write `INTEGRATION PASS` unless all core acceptance items are proven.
