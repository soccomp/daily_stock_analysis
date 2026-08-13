# DSA Lightweight Local Model A/B v1 — Evaluation Report

## Verdict

`LIGHTWEIGHT_LOCAL_MODEL_PROMISING_NEEDS_MORE_EVIDENCE`

The Owner-selected candidates were evaluated in a bounded, process-local MLX
window.  **Neither candidate is approved to replace the production
`Qwen3-14B-MLX-6bit` route now.**  Candidate A (`Qwen3-14B-MLX-4bit`) is
promising: it preserved the existing parser/integrity checks in the two
available persisted contexts and improved the near-comparable neutral-case
generation time by about 29–31%.  That is below the Mission's 35% / 75-second
replacement threshold.  Candidate B (`Qwen3-8B-MLX-6bit`) was faster, but a
BUY result omitted required entry, stop and target geometry; it is rejected
for further routing consideration under the current safety rule.

**Plain Owner answer:** lighter models **暂时不能** replace the current
Qwen3-14B-MLX-6bit.  **不建议** enter a production model-switch Mission from
this evidence.  Candidate A may be evaluated again only through a separately
approved, broader quality set; Candidate B needs its actionable-plan quality
problem resolved before any further consideration.

## Frozen baseline and scope

| Item | Evidence |
| --- | --- |
| Production model | `Qwen3-14B-MLX-6bit` through the existing loopback oMLX service |
| Existing comparable latency | Historical 14B-6bit Research wall time about 211–219 s; roughly 8–10 decode tok/s |
| Baseline routing after evaluation | Restored and healthy: `Qwen3-14B-MLX-6bit`, one loaded engine |
| Complete candidate replays | 4 of the permitted maximum 5 |
| Frozen semantics | Prompt, parser/repair policy, `enable_thinking=false`, temperature 0.7, 8192-token maximum, Brain/RiskPolicy, scheduler, Athena, execution and LIVE state |

No fresh production-baseline replay was run.  Candidate measurements use the
same current Analyzer system prompt and formatting, the existing production
parser and integrity checker, and persisted Research-only contexts.  They are
direct local MLX generation measurements, rather than an HTTP oMLX request;
therefore process-load time is reported separately and comparisons to the
historical end-to-end production wall time are directional rather than a claim
of identical transport/retry overhead.

## Owner-selected candidate inventory

| Candidate | Trusted artifact | Pinned revision | Identity / quantization verification | Local size |
| --- | --- | --- | --- | --- |
| A | `mlx-community/Qwen3-14B-4bit` | `a4d9b2df59d2c150bef02fcbe0d91046b7ca33a4` | `Qwen3ForCausalLM`; Qwen3; 4-bit, group size 64 | 7.8 GB |
| B | `mlx-community/Qwen3-8B-6bit` | `35a99712f90d6c2c9a2407a3857e104a46edd9e6` | `Qwen3ForCausalLM`; Qwen3; 6-bit, group size 64 | 6.2 GB |

Both are public, established MLX Community conversions of the Qwen3
Apache-2.0 model family.  Their combined 14.0 GB footprint is within the
Owner-authorized 20 GB download budget.  They remain evaluation-only assets
outside the production model directory and were never selected by DSA or the
production oMLX route.

## Contexts and isolation

The compact set used the only two qualifying persisted Research-only contexts:

1. a current neutral/watch case; and
2. a historical technically bullish (`buy_signal`) case whose prior final
   research action remained safely non-actionable.

No independent persisted degraded-data case met the Mission selection rule, so
none was fabricated.  The harness excluded PortfolioSnapshot, RiskPolicy,
quantity, account, broker and execution data; it made no persistence writes
and made no Bocha, cloud-model or paid-service call.

The successful serving-only maintenance window first identified the actual
launcher topology.  Two existing launchd labels could independently respawn
the loopback oMLX process: `com.athena.olmx` and `homebrew.mxcl.omlx`, both
with keep-alive semantics.  The oMLX CLI also daemonizes its listener, so
unloading only one label left an inherited `omlx-server` listener alive.

The accepted, reversible sequence was:

1. capture healthy production 14B-6bit state and confirm no active production
   Research request;
2. unload both pre-existing labels and verify their known listener is absent;
3. run each candidate only as a process-local MLX invocation, with no candidate
   HTTP endpoint and no DSA routing change;
4. reload the same two existing launchd definitions; and
5. verify the original healthy 14B-6bit loopback service and engine count.

The original launcher definitions were restored unchanged.  No DSA, Athena,
scheduler, trading, authentication, prompt, model or production configuration
file was changed.  Initial aborted isolation attempts returned no candidate
output and are not counted as replays.

## Measured results

All four returned text was passed through the existing Analyzer parser and
integrity checker.  No parser repair/retry was needed.  Prompt and completion
counts below are tokenizer counts; generation excludes the separately reported
model-load time.

| Candidate / context | Prompt / completion tokens | Load / generation | Decode tok/s | Parsed outcome | Quality gate |
| --- | ---: | ---: | ---: | --- | --- |
| A 14B-4bit / neutral | 6,811 / 1,752 | 1.46 s / 150.55 s | 11.64 | WATCH / HOLD | Pass: parser and integrity pass; summary and risk warning present |
| A 14B-4bit / bullish | 5,310 / 1,540 | 0.54 s / 128.87 s | 11.95 | HOLD / HOLD | Pass: parser and integrity pass; summary and risk warning present |
| B 8B-6bit / neutral | 6,811 / 1,767 | 1.24 s / 130.68 s | 13.52 | WATCH / HOLD | Pass for this non-actionable response |
| B 8B-6bit / bullish | 5,310 / 1,601 | 0.52 s / 120.21 s | 13.32 | BUY / BUY | **Fail:** entry, stop and target all absent |

For the closest neutral comparison, A saved about 60.5–68.5 s against the
historical 211–219 s baseline, or approximately 29–31%.  B saved about
80.3–88.3 s, approximately 38–40%, but cannot qualify because its BUY response
is not safely actionable.  Candidate decode rates were higher than the
historical 8–10 tok/s indication; this does not override the end-to-end
quality and replacement thresholds.

The known requirement is literal: a candidate `buy` or `add` needs positive
entry, stop and target values satisfying `stop < entry < target`.  Candidate
B's parser accepted the general response, but all three plan fields were null.
The evaluation therefore rejects it fail-closed; no Brain decision, mandate,
dispatch or broker operation was created.

## Resource and safety observations

The four process-local runs showed no swap increase during the controlled
window; the observed aggregate value declined modestly.  Candidate artifacts
are smaller than the existing 14B-6bit artifact, but this bounded evidence is
not a production memory-pressure certification.  The production loopback
service was restored before the next normal scheduler opportunity and remains
on the original 14B-6bit model.

At no point did the evaluation invoke DSA production analysis, change the
scheduler cadence, route a production request to a candidate, create an
InvestmentDecision/ExecutionMandate/ExecutionResult, or call Athena or a
broker.

## Decision table

| Question | Decision |
| --- | --- |
| Can either candidate replace production now? | No |
| Candidate A status | Promising but insufficiently faster for the replacement threshold; needs more representative quality evidence |
| Candidate B status | Rejected for actionable-plan completeness failure |
| Production route | Remains `Qwen3-14B-MLX-6bit` |
| Production switch recommended now? | No |
| Further replays used | No; one permitted replay remains, but no third qualifying persisted context was available |

## Verification and non-goals

- Four complete process-local candidate generations were run; the Mission cap
  of five was respected.
- Candidate outputs were parsed by the existing production parser/integrity
  checker with no repair required.
- Production oMLX health was rechecked after restoring the original launcher
  topology and model route.
- No source, runtime configuration, DSA, Athena, scheduler, RiskPolicy,
  broker, prompt or model-selection change is included in this PR.
- Deployment: none.

## Architecture review request

Please review the serving-supervisor finding and the bounded conclusion:
retain production 14B-6bit; treat A as evaluation-only pending a broader
quality set; reject B under the existing actionable-plan safety rule.  This PR
contains only this sanitized evidence report and awaits Architecture Review.
