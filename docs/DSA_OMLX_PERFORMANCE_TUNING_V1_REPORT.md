# DSA oMLX Performance Tuning v1 — Report

## Decision

- **Tuning verdict:** `OMLX_TUNING_BLOCKED_BY_RESOURCE_LIMIT`
- **是否建议把这个 oMLX 配置正式应用到生产：否。**
- **Recommended production serving-config diff:** none.

The installed server exposes plausible serving knobs, but the currently loaded
14B model is already constrained by Metal prefill headroom and non-zero swap
use.  A second model instance is unsafe; the only low-memory single-instance
candidate is not expected to improve the single-stream workload materially.
This mission therefore did not trade service stability for an uninformative
benchmark.  The original production configuration was never changed and is
the configuration still running at closeout.

## Exact baseline fingerprint

| Item | Sanitized observed value |
| --- | --- |
| Governance base | `athena-integration@636c71abde9692d5b834b5651a465b871b61a3c3` |
| M5 DSA application SHA | `8d538348d4ca9c4633a978f318faf9402119aaab` |
| oMLX version/install | `0.5.7`, Homebrew installation |
| Service command | Homebrew LaunchAgent running `omlx serve` |
| Bind/security | `127.0.0.1:8000`; API-key verification enabled |
| Model | `Qwen3-14B-MLX-6bit`, pinned/default, 6-bit unchanged |
| Model residency | pinned; model TTL 3600 seconds |
| Thinking | disabled; unchanged |
| Server concurrency | 2 max concurrent requests |
| Memory guard | custom 25GB guard ceiling |
| Cache | paged SSD cache enabled (18GB ceiling), hot cache disabled, 64 initial blocks |
| Exposed local knobs | concurrency, memory guard, paged SSD cache, hot cache, initial cache blocks; no installed `bench` subcommand |

The server was loopback-only throughout.  No authentication material, model
path, cache content, prompt, or runtime secret is reproduced here.

## Baseline performance evidence

Existing oMLX logs supplied a comparable baseline, so no baseline Analyzer
replay was needed.  The most recent 10 comparable Qwen requests had prompts
between roughly 6.6k and 7.2k tokens.

| Metric | Comparable baseline |
| --- | ---: |
| Model response wall time, median | 219.31 seconds |
| Model response wall time, range | 187.23–331.03 seconds |
| Completion tokens, median | 1,743 |
| Decode throughput, median | 8.8 tokens/sec |
| TTFT / distinct prefill throughput | not emitted by this installed server version |
| Prefix-cache evidence | available; aggregate Qwen cached prompt tokens are present, and logs show partial prefix reuse |

The broader 20-request window has a 218.50-second median response wall time
and a 79.58–416.85-second range.  Its very short prompt/output outlier is not
used as the primary comparable baseline.  Existing production log evidence
also shows the Analyzer's one bounded completion repair can produce a second
model response; that behavior is part of the frozen Research semantics and
was not tuned here.

## Memory and stability evidence

- Host physical memory: 32GB.
- Swap was already in use at baseline (about 3.5GB of a 4GB allocation).
- oMLX logs repeatedly recorded `adaptive_prefill_throttle`, with a 24.96GB
  Metal cap, requested prefill sizes reduced, and occasional pooled Metal
  buffer reclamation.
- The service was healthy and no oMLX crash/restart was observed during this
  assessment.  DSA health remained unchanged.

These facts make a concurrent second 14B test instance unsafe: it would add a
second model footprint while the existing single model is already being
prefill-throttled.  They also make memory-increasing cache candidates unsafe.

## Candidate profiles designed from installed options

| Profile | Exact serving difference from baseline | Expected mechanism | A/B decision and rollback |
| --- | --- | --- | --- |
| C1: serial admission | `--max-concurrent-requests 1` | Reduces contention/memory peaks only when requests overlap | Not tested: baseline workload is single-stream and the profile cannot plausibly produce the required >=20% latency reduction; baseline remains unchanged. |
| C2: hot cache | `--hot-cache-max-size 4GB` | May retain more reusable prefixes | Rejected before test: adds memory to a host already using swap and reporting prefill headroom pressure. Rollback would be removal of the flag. |
| C3: preallocated cache blocks | `--initial-cache-blocks 256` | May reduce dynamic cache-allocation overhead | Rejected before test: increases reserved cache pressure; current logs already grow cache blocks while memory guard throttles prefill. Rollback would be removal of the flag. |

`--memory-guard safe` was also considered but is more conservative by design
and has no credible single-request latency-improvement mechanism.  No profile
was applied, no oMLX service restart was performed, and no test port was
opened.

## A/B and quality result

No isolated A/B instance was started, and no single-instance temporary
serving restart was performed.  Consequently:

- new full Analyzer replays: **0 / 3**;
- no fresh generation microbenchmark was run;
- no parser/schema, completion-policy, structured-output, or action quality
  comparison was needed;
- no candidate can claim an absolute seconds-saved or percentage improvement.

This is a safety-constrained no-op result, not evidence that a candidate is
slower.  The existing production baseline is retained because it is the only
profile with observed quality and stability evidence under the current memory
conditions.

## Frozen-boundary and rollback confirmation

- DSA production source, prompt, generation semantics, model/quantization,
  configuration, service process, scheduler, Athena, RiskPolicy, Brain, and
  execution paths were not changed.
- No DSA restart, scheduler trigger, broker call, account mutation, cloud
  model, paid API, Bocha/search call, or trading operation occurred.
- LIVE remained unchanged and no SELL/REDUCE capability was enabled.
- oMLX bind and authentication were not weakened.
- Original oMLX serving configuration required no restoration because it was
  never modified.

## Next safe step

Do not apply a serving profile now.  A future separately authorized tuning
window should first establish materially more memory/swap headroom, then run a
single-factor isolated A/B with the same persisted Research context and the
existing non-production evaluation harness.

