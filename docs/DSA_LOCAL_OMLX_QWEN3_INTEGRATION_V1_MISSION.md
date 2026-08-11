# DSA Local oMLX Qwen3 Integration v1 — Codex Mission (Quota-Saving Phase A)

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a local-runtime integration across DSA LiteLLM routing, oMLX health, Analyzer structured generation, runtime restart/alignment, and Single Brain safety. Keep reasoning high enough to avoid configuration mistakes, but keep the mission deliberately narrow to conserve Codex quota.

---

# Mission Name

**额度节省版 Phase A：将 M5 本地 oMLX / Qwen3-14B-MLX-6bit 接入 DSA，证明核心 LLM 依赖可用，然后停止。**

## Canonical Source

Repository: `soccomp/daily_stock_analysis`

Target branch: `athena-integration`

Mission document was revised after commit `b84781a0f3d4ef8552694b1aa6aeb9e99466e585` specifically to reduce Codex usage.

Start from latest `origin/athena-integration` and record the exact base. The currently deployed application baseline before this integration is the PR #12 merge application commit:

`2ded7a711098667c3fd462d86d1f52b632a4923d`

---

# OWNER PRIORITY: CONSERVE CODEX QUOTA

The Owner's Codex quota is scarce. **Do not turn this into a broad benchmark, tuning, refactor, or soak mission.**

This Phase A answers only four questions:

1. Is the existing oMLX service healthy and safely loopback/auth protected?
2. Can DSA route its normal text generation only to local `Qwen3-14B-MLX-6bit` with dead cloud routes removed from the effective path?
3. Can the real DSA JSON generation contract and one representative Analyzer/report generation succeed through that local model?
4. Did the integration preserve Single Brain / simulation-only safety facts?

Once those are proven, **STOP** and post the closeout. Do not continue into deeper optimization without a new Owner instruction.

Explicitly **do not perform in Phase A**:

- 10-request soak
- 3-case Analyzer benchmark matrix
- full historical replay benchmark
- throughput comparison
- concurrency benchmarking
- long context benchmarking
- full backend CI gate unless a source change is actually required
- dependency upgrades
- speculative decoding / TurboQuant / draft-model experiments
- SSD KV-cache experiments
- Agent/tool-calling qualification unless current production actually depends on it
- cloud-provider recovery attempts
- scheduler acceleration or forced production analysis/trade

---

# Owner-provided runtime facts — verify briefly

The Owner reports:

- oMLX already runs on loopback `127.0.0.1:8000` with an OpenAI-compatible API.
- `/v1/models` currently returns `Qwen3-14B-MLX-6bit` as the only model.
- Direct chat generation already works.
- oMLX API authentication is enabled.
- Previously configured cloud LLM routes, including Alibaba/Qwen cloud access, are no longer usable.

Verify these facts on M5, but do not over-investigate a service that is already healthy.

The Owner supplied the oMLX API credential out-of-band. **Never commit, print, log, screenshot, paste into GitHub, or include the credential in closeout evidence.** Reuse the existing local secret from protected runtime configuration. Do not disable authentication. If the local credential cannot be safely reused without exposing or rotating it, that is an **OWNER HARD STOP**.

---

# Authority / safety boundary

This mission changes local model transport/configuration only.

Do not change:

- DSA Brain investment authority
- RiskPolicy
- PortfolioSnapshot contract
- sizing / target quantity semantics
- mandate / execution logic
- Athena source or deployment
- broker permissions
- `LIVE_TRADING=false`
- simulation-only mode
- SELL/REDUCE capability
- M3 scheduler cadence
- auth/network exposure

No forced trade. No forced BUY/ADD. Do not manually trigger an autonomous production M3 cycle solely for model testing.

If a natural cycle runs because of an ordinary DSA restart, observe and record it; do not retry or accelerate it.

---

# Expected DSA route

Prefer the repository's existing OpenAI-compatible LiteLLM channel path. Do **not** invent a new oMLX provider unless the existing generic channel path is proven incompatible.

Expected effective shape, after verifying current config parser semantics:

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=

LLM_CHANNELS=omlx
LLM_OMLX_PROTOCOL=openai
LLM_OMLX_API_SURFACE=chat_completions
LLM_OMLX_BASE_URL=http://127.0.0.1:8000/v1
LLM_OMLX_API_KEY=<LOCAL SECRET; NEVER PRINT OR COMMIT>
LLM_OMLX_MODELS=Qwen3-14B-MLX-6bit
LITELLM_MODEL=openai/Qwen3-14B-MLX-6bit
```

Do not blindly paste this block. Inspect current M5 `.env` / runtime config and use the exact syntax supported by the current DSA parser.

The effective normal text-generation route must contain **only the local oMLX deployment**. Do not delete unrelated secret material just to clean the file, but remove/disable dead cloud deployments from the effective routing and fallback path so DSA does not waste time or quota failing over to them.

Do not reroute vision to this text model. Do not enable Agent mode just for testing.

---

# Phase A1 — Minimal preflight and backups

Before mutation:

1. Record exact GitHub base and current M5 running DSA source SHA.
2. Back up the DSA runtime `.env` / relevant runtime config with secure permissions.
3. If changing any oMLX setting, back up the corresponding local settings file first.
4. Record `com.dsa.webui` state, loopback `127.0.0.1:8080`, and current Single Brain readiness facts needed for post-change comparison.
5. Verify oMLX listener is loopback-only, authentication is enforced, `/v1/models` returns the expected model, and one short authenticated chat request returns non-empty final content.

Do not expose secrets in command output or evidence.

---

# Phase A2 — Minimal oMLX review, not a tuning project

Inspect the installed oMLX version and current settings only far enough to detect obvious DSA reliability risks.

For Phase A:

- keep effective DSA generation concurrency at **1**
- do not raise oMLX concurrency
- do not change context size unless the real Analyzer prompt cannot fit
- do not enable experimental acceleration/cache features
- do not conduct benchmark sweeps

If the installed oMLX version already supports an easy, reversible per-model/profile option to disable Qwen3 thinking **without duplicating weights or changing model files**, you may create/use a DSA-specific non-thinking profile **only if it is a routine configuration action** and immediately verify it with one JSON smoke. Otherwise leave the base model as-is and report `non-thinking profile deferred to Phase B`.

Likewise, only change TTL / keep-loaded / memory guard if the existing value is obviously unsafe or prevents the required smoke. Otherwise record a short recommendation for a future Phase B instead of spending quota optimizing it now.

---

# Phase A3 — Make local oMLX the only effective DSA text-generation route

1. Inspect current effective DSA LLM config without printing secret values.
2. Configure `GENERATION_BACKEND=litellm` through one explicit local oMLX OpenAI-compatible channel.
3. Disable backend/model fallback to dead cloud routes.
4. Ensure obsolete Alibaba/Qwen/cloud deployments are absent from the **effective route**.
5. Run DSA structured config validation.
6. Inspect the effective model/provider route and prove it points to loopback oMLX.
7. Restart only the DSA service required to load the new config. Do not restart Athena.
8. Reconfirm DSA serves `127.0.0.1:8080` and launchd is healthy.

If current `AGENT_LITELLM_MODEL` explicitly points to a dead cloud model, do not automatically claim Qwen3 supports Agent tools. If Agent mode is not in current production use, leave Agent capability out of Phase A and disclose that it was not qualified.

---

# Phase A4 — Minimum DSA-native LLM qualification

Connection success is not enough, but keep the qualification small.

## Test 1 — DSA generation-backend JSON smoke

Use the existing DSA generation-backend JSON smoke path/service against the real oMLX route.

Require:

- request reaches `127.0.0.1:8000`
- non-empty final content
- required JSON parses through the existing DSA smoke contract
- no cloud fallback/request
- no secret in diagnostics

## Test 2 — ONE representative real Analyzer/report replay

Run **one** non-trading Analyzer/report generation using the real production prompt-building + response parsing/schema/integrity path.

Prefer a saved/sanitized historical input or the narrowest representative fixture that includes normal technical + news/research synthesis.

Record only the essentials:

- approximate prompt/context size
- wall time
- raw JSON success or repair used
- existing `AnalysisReportSchema` / parser success
- integrity retry count
- whether reasoning wrapper/content separation caused any issue
- brief Chinese output sanity check: conclusion/reasons not obviously contradictory and no fabricated missing-data certainty

Acceptance: the final report must pass the existing DSA parser/schema/integrity path. One bounded normal retry already supported by DSA is acceptable; do not hide repeated incompatibility behind endless retries.

## Optional Test 3 — ordinary generation

Only if it is trivial and uses the same already-loaded generation path, run one short ordinary non-trading `generate_text()`/market-review-style smoke. Skip it if doing so requires substantial setup or investigation; report `deferred` rather than spending Codex quota.

---

# Phase A5 — Safety recheck

After the DSA config/restart, prove the mission did not expand trading capability:

- Athena still READY / simulation-only
- `LIVE_TRADING=false`
- DSA execution mode still `SIMULATION_EXECUTION`
- simulation authorization unchanged
- exactly one M3 scheduler authority
- cadence still exactly 3600 seconds
- P1A/P1B remain OFF
- pending execution did not increase because of this test harness
- connected Athena portfolio remains read-only / not merged into manual ledger
- no RiskPolicy / sizing / mandate / execution / broker / SELL/REDUCE / auth/network change

Do not run broad unrelated regression suites for this config-only mission.

---

# Source-change gate

The expected outcome is **configuration-only**.

If the existing generic OpenAI-compatible channel or parser cannot handle oMLX/Qwen3 and a DSA source fix is genuinely required:

**ARCHITECTURE REVIEW GATE**

- create a new branch from latest `origin/athena-integration`
- implement only the smallest generic compatibility fix
- add focused tests only
- push a **Draft PR**
- do not merge
- do not deploy the source fix
- stop and report `SOURCE FIX REQUIRED`

Do not spend quota trying multiple speculative source rewrites.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine reversible blockers may be fixed without Owner relay, including:

- stale local `.env` LLM route values
- dead cloud routes still active
- DSA restart/port release timing
- oMLX cold load
- local config syntax mistakes
- focused smoke harness issues

Keep the fix local, minimal, reversible, and inside this mission.

---

# OWNER HARD STOP

Stop before:

- exposing oMLX/DSA beyond loopback
- disabling oMLX authentication
- rotating/changing the API key because the existing credential cannot be safely reused
- enabling LIVE
- enabling SELL/REDUCE
- changing RiskPolicy/investment authority
- changing scheduler cadence
- changing Athena source/deployment
- destructive migration/model deletion
- installing experimental oMLX builds or patching oMLX source
- merging/deploying any source-fix PR

---

# Phase A acceptance

Write **`PHASE A PASS`** only if all are true:

- oMLX loopback + auth + model health verified
- DSA effective normal text-generation route is local oMLX only
- dead cloud routes are absent from the effective fallback path
- DSA JSON generation smoke passes
- one real representative Analyzer/report generation passes existing parser/schema/integrity checks
- DSA restarts healthy
- Single Brain / Athena simulation safety state is unchanged
- no source fix is needed

Use **`PHASE A PASS WITH LIMITATION`** if core generation works but a non-core item is deferred, such as non-thinking profile tuning, Agent tools, ordinary market-review smoke, or deeper oMLX optimization.

Use **`SOURCE FIX REQUIRED`** if core DSA Analyzer integration cannot pass without source change.

---

# STOP CONDITION — IMPORTANT

After Phase A acceptance, **STOP THE TASK**.

Do not proceed into deeper oMLX tuning, 10-request soak, multiple Analyzer replays, performance benchmarking, or qualification of more models. Those belong to a future **Phase B** only after ChatGPT/Owner reviews the Phase A evidence.

---

# Canonical closeout

Repository Issues are disabled. Post one sanitized closeout to the merged DSA PR #12 conversation titled:

`M5 local oMLX/Qwen3 integration closeout — quota-saving Phase A`

Include only:

- `PHASE A PASS`, `PASS WITH LIMITATION`, or `SOURCE FIX REQUIRED`
- exact GitHub base and running M5 source SHA
- oMLX version/install mode; loopback/auth status
- exact active model/profile ID
- sanitized effective DSA LLM route, with no API key
- confirmation dead cloud routes are not effective fallbacks
- one direct oMLX smoke result
- DSA JSON smoke result
- one Analyzer replay result and parser/integrity outcome
- optional ordinary-generation result if run
- any minimal oMLX setting changed; otherwise say deeper tuning deferred
- DSA launchd/runtime state
- Single Brain/Athena safety facts
- limitations/deferred Phase B items
- rollback backup references in sanitized form

Never include the API key, balances, account identifiers, full holdings, raw private prompts/news payloads, or secret-bearing logs.
