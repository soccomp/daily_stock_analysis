# DSA Local Qwen Final Usability v1 — Evaluation Report

## Decision

- **Practical usability verdict:** `LOCAL_QWEN_USABLE_WITH_LIMITATIONS`
- **Cloud decision:** `CLOUD_TRIAL_OPTIONAL_NOT_REQUIRED`
- **能不能用：能。**
- **好不好用：能用但有明显限制。**
- **现在是否值得付费做云模型 A/B：不必现在付费；如 Owner 希望缩短研究时延或提高可操作信号覆盖，可作为可选的后续比较，而不是当前的安全或质量修复。**

The evidence does not identify a repeated local-Qwen parser or structural-output defect.  The current deterministic, fail-closed downstream path continues to contain sparse or non-actionable Research safely.

## Exact provenance and scope

- Governance base: `athena-integration@56bb725e9beb7fb0c89fdfdcf238a5ac88e25151`.
- M5 application evidence source: `8d538348d4ca9c4633a978f318faf9402119aaab`.
- Current route observed from the effective configuration: `openai/Qwen3-14B-MLX-6bit`, through existing loopback oMLX, with zero configured fallback models.
- Production `src/` changed: **no**.  The only executable addition is a non-production `tools/local_qwen_evaluation.py` transport helper plus focused tests.
- New local-Qwen Analyzer attempts in this mission: **2**, the permitted maximum.  No cloud model, paid API, Bocha, search refresh, scheduler cycle, Brain, mandate, broker, or execution call was initiated by this evaluation.

## Phase A — PR #17 replay observability root cause

PR #17 used a direct, in-process Analyzer invocation embedded in an interactive command.  It had no explicit child exit status, timeout record, exception envelope, result marker, or durable sanitized output channel.  When the interactive parent detached before local oMLX generation completed, its child continued but no evaluator-owned channel remained to return a final `AnalysisResult`.  This was an **evaluation harness observability limitation**, not evidence of a Qwen failure.

The new non-production helper resolves that boundary by running the Analyzer in an isolated child session and emitting a sanitized JSON envelope.  It distinguishes `result`, `child_error`, `timeout`, and `transport_error`; it can atomically persist the same sanitized envelope to an evaluator-supplied temporary result file when parent stdout capture is unavailable.  Evaluation mode monkeypatches only `persist_llm_usage`, preventing telemetry writes while retaining the production Analyzer/parser code path.

Focused proof:

- mocked valid `AnalysisResult` survives child transport and sanitized serialization;
- child exceptions are surfaced explicitly;
- timeout is distinct from model/parser failure;
- durable sanitized child-result fallback is readable;
- evaluation-mode usage persistence is suppressed by a focused regression test;
- the tool has no authoritative portfolio, policy, trading, or execution imports.

## Phase B — current practical usability evidence

### Evidence window

The newest 30 completed `analysis_history` records were inspected read-only.  Twenty-nine are local-Qwen Research results; one is a market-review record.  All 30 persisted raw-result payloads are parseable.  The local-Qwen model identity recorded by all 29 Research records is `openai/Qwen3-14B-MLX-6bit`.

| Dimension | Read-only evidence | Assessment |
| --- | --- | --- |
| Route availability | 29/29 completed local-Qwen Research records persisted with `success=true` and no stored error | operationally usable |
| Structured result persistence | 29/29 local-Qwen raw results parseable; no stored failure | usable |
| Bounded completion | In the available same-day local-Qwen log segment, 6 of 8 Analysis calls used the existing one bounded completion repair; all later persisted successfully | meaningful latency/format-completeness limitation, safely contained |
| Generation latency | Observable per-call response durations span about 187–417 seconds in that log segment | high but below the 3600-second normal cadence; post-Research authoritative Snapshot refresh architecture prevents stale pre-Research account truth from being used downstream |
| Natural actionable-long samples | 0 | quality of `buy/add` price plans remains unproven, not failed |

### Normalized action distribution

| Action | Count among newest 30 records |
| --- | ---: |
| `buy` | 0 |
| `add` | 0 |
| `watch` | 25 |
| `hold` | 4 |
| `avoid` / `alert` / `reduce` / `sell` | 0 |
| missing (market review) | 1 |

A high `watch/hold` rate is not treated as a model defect.  The prior natural-cycle evidence confirms that a structured `watch` becomes canonical Brain `HOLD` with zero delta and zero execution artifacts.

### Actionable-long quality

There are no naturally existing `buy/add` samples to score.  Accordingly, there is no basis to claim that an executable long plan passed or failed `entry > 0`, `stop > 0`, `target > 0`, `stop < entry`, and `target > entry`; the report does not infer these conditions from non-actionable report price references.

## Phase C — bounded replay status

Two persisted Research-only contexts, each already marked by the repository's technical input as a bullish candidate, were selected without synthetic prompting.  Both were submitted through the current local route after mocked transport proof.  No third call was made.

The interactive evaluation host detached from each long-running parent process before its child could return stdout; these attempts therefore cannot be scored as model output, parser, or price-plan failures.  The failure is the same external parent-lifecycle observability issue isolated in Phase A.  The newly added persistent child-result path prevents that loss for a future offline evaluator run, but the replay cap prohibits repeating either call in this mission.

## Top reasons for the decision

1. **It demonstrably works in the present Research role:** 29 consecutive persisted local-Qwen Research results were successful and parseable in the bounded window.
2. **The material limitation is operational, not unsafe:** typical generated responses take roughly 3–7 minutes and the existing one bounded completion repair appears frequently; these are safely constrained by current completion and downstream fail-closed logic.
3. **Actionable-long quality is still unmeasured:** there are no natural `buy/add` outputs and the two permitted offline attempts have no recoverable output record.  This warrants more natural evidence, not a claim that local Qwen is broken or an immediate paid-cloud remedy.

## Frozen-boundary confirmation

No production source semantics, prompt, model identity, quantization, model parameters, runtime configuration, oMLX service, Bocha/search route, Snapshot contract, RiskPolicy, scheduler topology/cadence, Athena, execution boundary, LIVE setting, or SELL/REDUCE capability changed.  No deployment or restart occurred.  The evaluation introduced no portfolio, manual-ledger, mandate, submission, cancellation, retry, reconciliation, or broker mutation.
