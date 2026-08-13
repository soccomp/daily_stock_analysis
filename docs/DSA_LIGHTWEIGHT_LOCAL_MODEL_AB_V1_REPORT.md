# DSA Lightweight Local Model A/B v1 — Evaluation Report

## Verdict

`LIGHTWEIGHT_AB_BLOCKED_BY_RESOURCE_OR_ISOLATION`

The two Owner-selected local MLX artifacts were obtained and verified, but no
candidate full Analyzer replay was accepted as evidence.  On the current M5,
the installed oMLX serving stack cannot be stopped reliably enough to prove a
single-model candidate evaluation window without risking a production DSA
route collision or concurrent-model memory pressure.  The conservative result
is therefore **not** a quality or speed comparison and must not be interpreted
as a rejection of either candidate.

**Plain Owner answer:** the lighter models **暂时不能** replace the current
Qwen3-14B-MLX-6bit.  **不建议** enter a production model-switch Mission from
this evidence.  A future A/B needs a separately accepted isolation mechanism.

## Frozen baseline

| Item | Evidence |
| --- | --- |
| Production model | `Qwen3-14B-MLX-6bit` through the existing loopback oMLX service |
| Reviewed comparable latency | median Research wall time about 211–219 s; roughly 8–10 decode tok/s |
| Latest untouched natural cycle during this work | completed at 2026-08-13 23:50:52 local time; production model remained 14B-6bit |
| Frozen semantics | Prompt, schema/parser/repair policy, `enable_thinking=false`, generation settings, Brain/RiskPolicy, scheduler, Athena, execution and LIVE state |

No fresh 14B baseline replay was run.  The production service was restored to
the same healthy default model after every controlled attempt.

## Owner-selected candidate inventory

| Candidate | Trusted artifact | Pinned revision | Identity / quantization verification | Local size | License / source basis |
| --- | --- | --- | --- | --- | --- |
| A | `mlx-community/Qwen3-14B-4bit` | `a4d9b2df59d2c150bef02fcbe0d91046b7ca33a4` | `Qwen3ForCausalLM`, Qwen3, 4-bit group size 64 | 7.8 GB | Established MLX conversion maintainer; public Qwen3 Apache-2.0 model family metadata |
| B | `mlx-community/Qwen3-8B-6bit` | `35a99712f90d6c2c9a2407a3857e104a46edd9e6` | `Qwen3ForCausalLM`, Qwen3, 6-bit group size 64 | 6.2 GB | Established MLX conversion maintainer; public Qwen3 Apache-2.0 model family metadata |

The combined 14.0 GB footprint is within the Owner-authorized 20 GB download
budget.  Both artifacts are evaluation-only assets outside the production
model directory and were never selected by DSA or the production oMLX route.

## Context and harness preparation

The planned compact set used two persisted Research-only contexts:

1. a current neutral/watch case; and
2. a historical technically bullish (`buy_signal`) case whose prior final
   research action remained safely non-actionable.

There was no independent persisted degraded-data case that satisfied the
Mission selection rule, so none was fabricated.  The isolated harness built
the existing Analyzer system prompt and prompt formatting from those persisted
contexts, with no PortfolioSnapshot, RiskPolicy, quantity, account, broker or
execution data.  It suppressed evaluation persistence and did not call Bocha,
cloud models, or any paid service.

## Isolation evidence and stop condition

The approved preference was direct/process-local MLX inference.  It was used
instead of a candidate HTTP endpoint because the oMLX CLI ignored the intended
candidate port/model-directory isolation and wrote global serving settings.
That attempt was detected before any successful candidate request; the original
settings and 14B-6bit health were restored immediately.

For direct inference, the controlled maintenance sequence was:

1. confirm no active production Research request;
2. capture healthy production 14B-6bit state;
3. temporarily unload the Homebrew launchd service and stop its known 8000
   listener;
4. verify no listener on 8000; then load the candidate in a process-local MLX
   subprocess; and
5. restore Homebrew oMLX and verify the original healthy 14B-6bit service.

Despite steps 1–4, a separate parentless `omlx-server` process reappeared on
the production loopback port during each candidate load.  Its lifecycle was
not attributable to the unloaded launchd label.  Continuing would leave the
production route unavailable or introduce concurrent model residency under the
known M5 swap pressure.  That violates the Mission isolation requirement, so
each incomplete candidate process was stopped before it returned a response.

| Measurement | Result |
| --- | --- |
| Completed full Analyzer replays | 0 of 5 permitted |
| Candidate responses parsed | 0 |
| Candidate quality/repair evidence | none — no response was accepted |
| Candidate-memory/swap comparison | none — concurrent residency was rejected as unsafe |
| Production oMLX restored | yes, healthy `Qwen3-14B-MLX-6bit`, one loaded model |
| Production DSA route changed | no |
| DSA restart / scheduler change | no / no |
| AnalysisHistory or LLM usage written by evaluation | no |
| Athena, Brain, RiskPolicy, mandate, execution or ledger mutation | none |

## Required comparison

| Model | Comparable wall time | Seconds saved / change | Decode throughput | Memory/swap | Parser / repair | Research-quality finding | Actionable-long plan |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| Qwen3-14B-MLX-6bit baseline | 211–219 s median | baseline | ~8–10 tok/s | existing M5 swap pressure | usable reviewed production baseline | usable with documented limitations | no new sample in this Mission |
| Qwen3-14B-MLX-4bit | not measured safely | not measured | not measured | not measured | no candidate output | no conclusion | not observed |
| Qwen3-8B-MLX-6bit | not measured safely | not measured | not measured | not measured | no candidate output | no conclusion | not observed |

## Minimal next step

Do not alter the production model from this report.  If a later Owner-approved
Mission needs the comparison, first provide a supported serving/process
isolation mechanism that can prove all of the following before any candidate
generation:

- an unloaded production oMLX supervisor cannot respawn a listener;
- the candidate process has no production DSA route or shared global serving
  state;
- production 14B-6bit can be restored and health-checked before the next
  natural Research window; and
- candidate residency is measured without concurrent 14B memory pressure.

That is an operational isolation prerequisite, not a request to weaken model,
prompt, Snapshot, Brain, RiskPolicy, scheduler or execution semantics.

## Safety closeout

- Production application source and configuration: unchanged.
- Production oMLX route: restored to `Qwen3-14B-MLX-6bit`; `enable_thinking`
  remains false.
- DSA scheduler: unchanged; no forced cycle.
- Athena: untouched; simulation/LIVE boundaries untouched.
- No cloud/paid model, Bocha/search refresh, broker/account/manual-ledger
  mutation, mandate, dispatch, cancel, retry or reconciliation operation.
- No deployment or production model switch.
