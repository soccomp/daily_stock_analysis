# DSA Local Qwen Actionable Research Quality v1 — Evaluation Report

## Scope and immutable baseline

- Governance base: `athena-integration@c0ab6480a57b9b8e84cf88f19296c9bff2685b86`.
- Evaluated M5 application runtime: `8d538348d4ca9c4633a978f318faf9402119aaab`.
- Local route observed from effective runtime configuration: `openai/Qwen3-14B-MLX-6bit` through the existing loopback oMLX OpenAI-compatible route.  The configured fallback-model count was zero.
- This is an evaluation only.  It did not change application source, prompt, model parameters, configuration, scheduler, Athena, PortfolioSnapshot, RiskPolicy, account state, or execution behavior.

## Phase A — persisted historical evidence

The evidence window was the 30 newest completed `analysis_history` records, ordered by persisted identifier descending: reports `94` through `65`.  Twenty-nine are Research records and one is a market-review record.  All 30 persisted `raw_result` values were parseable.

| Normalized final action | Count |
| --- | ---: |
| `watch` | 25 |
| `hold` | 4 |
| absent (market review) | 1 |
| `buy` / `add` | 0 |

For a broader sanity check, all 94 persisted historical records also contained no normalized `buy` or `add` action (`watch`: 72, `hold`: 14, absent: 8).  Therefore Phase A supplied zero actionable-long local-Qwen samples and did not meet the two-sample stop rule.  Per-actionable price-plan/Brain evidence is consequently not applicable: no historical `buy/add` output existed to score.

Generation latency and bounded-completion/repair count are not persisted in a per-analysis record that can be attributed to these historical samples; this is recorded as unavailable rather than inferred.

## Phase B — bounded offline local replay

Phase B was required.  Two existing, independent persisted Research-only contexts were selected because their already-persisted deterministic technical evidence was marked `buy_signal=买入`; no synthetic bullish input was created.

| Replay | Persisted source report | Context selection basis | Route | Result available to evaluator | Actionable scoring |
| --- | ---: | --- | --- | --- | --- |
| 1 | `63` | persisted bullish technical candidate, prior date/context | current local Qwen loopback route | no serialised `AnalysisResult` was returned to the isolated evaluator after the request | not scoreable |
| 2 | `81` | persisted bullish technical candidate, separate later context | current local Qwen loopback route | no serialised `AnalysisResult` was returned to the isolated evaluator after the request | not scoreable |

Exactly two new Analyzer replay attempts were made, the mission maximum.  They called the existing Analyzer and parser path with only the persisted enhanced Research context plus its persisted news text.  The isolated process disabled usage-telemetry persistence so the evaluation did not write analysis or LLM-use records.  No Search, Bocha, web refresh, PortfolioSnapshot, account state, RiskPolicy, Brain, mandate, broker, or scheduler path was invoked.

Both attempts reached the current configured local model route, but neither yielded a serialised final `AnalysisResult` to the evaluation process.  No parser/schema/content-integrity outcome, final action, entry, stop, target, latency record, or completion/repair count can safely be claimed from either attempt.  This is **not** classified as a Qwen structured-output defect because the model output itself was not available for inspection; equally, it is not evidence that an executable price plan was produced.

Read-only post-checks found the persisted analysis-history count unchanged at 94, its maximum identifier unchanged at 94, and no new attributable LLM-usage record.  No execution artifact was created.

## Scorecard and conclusion

There are fewer than two scoreable actionable-long samples after the allowed Phase A and Phase B evidence collection.  The required executable-long criteria (`entry > 0`, `stop > 0`, `target > 0`, `stop < entry`, `target > entry`) therefore have no PASS or FAIL samples; they must not be inferred from neutral Research outcomes or technical-candidate selection.

- **Verdict:** `INSUFFICIENT_ACTIONABLE_EVIDENCE`
- **Cloud-model recommendation:** `DEFER_DECISION_MORE_NATURAL_EVIDENCE_NEEDED`

This report does not recommend a paid-cloud A/B trial.  It has not isolated a repeated model-output structural weakness after the PR #16 Research-to-Brain repair.

## Safety confirmation

- The running service remained `main.py --webui-only`; no restart or deployment occurred.
- No scheduler configuration or cadence changed; no cycle was forced.
- No cloud model, paid API, Bocha, or web search was called for the evaluation.
- `LIVE_TRADING`, SELL/REDUCE capability, broker permissions, and all Single Brain decision/execution boundaries were untouched.
- No portfolio, manual ledger, mandate, submission, cancellation, retry, reconciliation, or broker mutation occurred.

