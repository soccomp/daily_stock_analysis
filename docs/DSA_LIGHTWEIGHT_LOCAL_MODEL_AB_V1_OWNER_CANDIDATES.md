# DSA Lightweight Local Model A/B v1 — Owner Candidate Selection

## Governance

This file is an Owner-approved candidate-selection addendum to:

`docs/DSA_LIGHTWEIGHT_LOCAL_MODEL_AB_V1_MISSION.md`

It narrows the candidate-discovery freedom in that Mission. All original safety, isolation, replay-cap, no-production-switch, and no-deployment boundaries remain in force.

Canonical base when this addendum was created:

`athena-integration@41fdaf1ee0a647c72859a459a67d20bb1b46c644`

## Owner-selected candidates

Test exactly these two logical candidates, in this order, if a trusted MLX-compatible artifact with clear identity/license is available:

1. **Candidate A — Qwen3-14B-MLX-4bit**
   - same Qwen3-14B parameter class as production;
   - 4-bit quantization instead of current 6-bit;
   - purpose: isolate the effect of more aggressive quantization while preserving model capacity/family.

2. **Candidate B — Qwen3-8B-MLX-6bit**
   - same Qwen3 family;
   - smaller 8B parameter class;
   - preserve 6-bit quantization;
   - purpose: isolate the effect of reducing model size while keeping the less aggressive quantization class.

Current production baseline remains:

**Qwen3-14B-MLX-6bit**

Do not substitute another model family, 7B model, 8B-4bit model, or other quantization in this Mission without a new Owner decision.

If either selected logical candidate has no trustworthy/compatible artifact or has ambiguous license/model identity, document that candidate as unavailable and continue with the other one. Do not silently replace it.

## Why these two candidates

The matrix deliberately changes one major variable at a time:

| Model | Parameter-size change | Quantization change | Main question |
| --- | --- | --- | --- |
| Production Qwen3-14B-6bit | baseline | baseline | current quality/latency reference |
| Qwen3-14B-4bit | none | 6bit → 4bit | can lower weight precision reduce memory/decode cost without meaningful Research-quality loss? |
| Qwen3-8B-6bit | 14B → 8B | none | can a smaller same-family model materially accelerate Research while retaining DSA quality? |

Do not test Qwen3-8B-4bit in v1. It changes both parameter capacity and quantization at once and would make a quality regression difficult to attribute.

## Download authorization and budget

Owner authorizes Codex to download the two selected **free local model artifacts** only when needed for this offline A/B, subject to all of the following:

- trusted official publisher or established MLX conversion-maintainer artifact;
- clear Qwen3 model identity and quantization metadata;
- no paid access or cloud inference;
- at most the two selected candidate artifacts;
- total new candidate artifact footprint should remain **<= 20 GB** unless actual trusted artifacts exceed that bound, in which case STOP and report the required size before downloading;
- record sanitized artifact identity, parameter class, quantization, source category, and on-disk size;
- never expose secrets/tokens;
- do not delete or overwrite the current production Qwen3-14B-6bit artifact.

Downloaded candidates are evaluation assets only. This authorization is **not** production deployment authorization.

## Isolation preference for M5 32GB

Because prior evidence showed non-zero swap and prefill pressure with the current 14B model, do not assume two 14B-class models can safely remain loaded concurrently.

Before loading Candidate A or B, inspect current memory/swap state.

Preferred order:

1. use a direct/process-local MLX evaluation path if it can be isolated safely from production DSA routing;
2. otherwise use the original Mission's controlled sequential serving-only maintenance window;
3. do not load a second model concurrently if expected combined footprint would cause material swap-thrash/OOM;
4. production DSA must never naturally route to Candidate A or Candidate B;
5. production Qwen3-14B-6bit route/config must be restored and health-checked before the next natural DSA Research window.

No DSA restart, scheduler-cadence change, or forced scheduler cycle is authorized.

## Evaluation order

Run Candidate A first because it preserves 14B model capacity and tests the lower-risk hypothesis: whether 4-bit quantization alone solves enough of the memory/decode bottleneck.

Then run Candidate B if resource/isolation conditions remain safe.

Use the same persisted Research-only contexts and frozen production prompt/schema/generation semantics specified by the parent Mission.

## Decision interpretation

Preferred outcome hierarchy:

1. If **14B-4bit** meets the speed threshold with essentially preserved structured/Research quality, prefer it over downsizing because it retains 14B capacity.
2. If **8B-6bit** is substantially faster and still passes all DSA quality/safety gates, it may be the better long-term M5 model despite lower parameter count.
3. If 14B-4bit is not fast enough and 8B-6bit materially degrades Research quality, retain 14B-6bit and conclude current M5 has a practical local-model ceiling for this workload.

The report must keep per-candidate conclusions separate so we can distinguish:

- quantization effect; and
- parameter-size effect.

## Required final comparison

The final report must include one concise table with at least:

- Qwen3-14B-6bit baseline;
- Qwen3-14B-4bit;
- Qwen3-8B-6bit;
- comparable wall time / seconds saved / percentage change;
- decode throughput where available;
- peak memory/swap behavior;
- parser/schema success;
- repair count;
- Research quality notes;
- actionable-long plan validity when observed;
- final recommendation.

Stop at the same parent-Mission gate:

`ARCHITECTURE REVIEW GATE — LIGHTWEIGHT_LOCAL_MODEL_AB_V1_READY`

No merge, production model switch, or deployment.
