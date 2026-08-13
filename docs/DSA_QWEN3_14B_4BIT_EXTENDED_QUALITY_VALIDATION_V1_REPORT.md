# DSA Qwen3-14B-4bit Extended Quality Validation v1 — Report

## Verdict

`QWEN3_14B_4BIT_NOT_READY`

The frozen candidate produces structurally parseable output, but it is not safe
to advance to a production-switch Mission. The expanded set contains a BUY
result with no entry, stop or target, and multiple results contain
capital-allocation language such as suggested position sizing. Both outcomes
violate the existing Research-only boundary. Production remains
`Qwen3-14B-MLX-6bit`.

**Owner answer:** 14B-4bit 的 Research 质量是否足够替代 14B-6bit：**否**。
是否建议进入生产模型切换 Mission：**否**。

## Scope and frozen candidate

| Item | Value |
| --- | --- |
| Governance base | `athena-integration@acf9836194ebfe64d8a57ebd22d3a9f36a15a5f3` |
| Prior evidence | PR #21, merged at `7ad55f9dfe8bc78314b8bb1fb0144ccb8d7c86e2` |
| Candidate | `mlx-community/Qwen3-14B-4bit` |
| Pinned artifact revision | `a4d9b2df59d2c150bef02fcbe0d91046b7ca33a4` |
| Candidate scope | Offline process-local MLX evaluation only |
| Production route after evaluation | Healthy `Qwen3-14B-MLX-6bit`, one loaded engine |

No other candidate was downloaded or evaluated. Qwen3-8B-6bit was not rerun.
Prompt, model settings (`enable_thinking=false`, temperature 0.7, 8192-token
maximum), parser, schema, integrity/repair policy, DSA source, Athena,
scheduler, RiskPolicy, Brain and execution semantics were unchanged.

## Isolation and rollback evidence

The PR #21 pattern was reused: the two known keep-alive launchd labels
(`com.athena.olmx` and `homebrew.mxcl.omlx`) were unloaded, the known loopback
listener was confirmed absent, and the candidate was loaded only in a local MLX
process. No candidate HTTP endpoint was exposed to DSA.

Each accepted replay used its own bounded maintenance window and restored both
original launcher definitions before the next replay. The final health check
confirmed the original 14B-6bit route with one loaded engine. An early
non-interactive wrapper returned before a native child exited; its unaccepted
children were explicitly terminated, production health was restored, and the
accepted replays then ran one-at-a-time with process-exit checks. This is
operational evidence only and does not count as a model result.

No DSA restart, scheduler change, forced cycle, production model routing,
Bocha/search refresh, cloud/paid inference, Athena call, broker action, account
mutation, mandate, dispatch, retry or reconciliation operation occurred.

## Context inventory and replay count

Six completed candidate replays were assessed: two accepted PR #21 replays and
four new persisted Research-only contexts. No account, PortfolioSnapshot,
RiskPolicy, quantity or broker input was supplied to the candidate.

| Category | Evidence source | Candidate outcome | Coverage conclusion |
| --- | --- | --- | --- |
| Neutral / watch-hold | PR #21 persisted context | WATCH / HOLD | Covered |
| Bullish actionability candidate | PR #21 technical-bullish context | HOLD / HOLD | Covered conservatively; no BUY was forced |
| Risk / degraded-data | Partial technical/data-quality context | WATCH / HOLD | Covered |
| Regime-sensitive / market structure | Market-structure and bearish-technical context | WATCH / HOLD | Covered |
| Technical conflict / mixed signal | Weak-bullish, confirmation-required context | WATCH / HOLD | Covered |
| News-heavy / catalyst-risk | Persisted multi-event news context | BUY / BUY | Covered; failed actionable-long gate |

No market fact or account state was fabricated. The current Mission added four
complete candidate generations; combined total is six and remains below the
cap of eight.

## Structured reliability and actionability gates

| Measure | Result |
| --- | --- |
| Analyzer/parser structured object | 6 / 6 returned successfully |
| Existing integrity checker | 6 / 6 passed; no missing required fields reported |
| Bounded completion/repair | 0 / 6 required repair |
| Unrecognized action or SELL/REDUCE capability | 0 observed |
| Actionable-long exercised | Yes — one BUY result in the news-heavy context |
| Legal complete BUY/ADD plan | **0 / 1** — the BUY had null entry, stop and target |
| Research-role discipline | **Fail** — repeated suggested-position / allocation wording |

Generic parser/integrity pass is not enough for readiness. The news-heavy BUY
failed the literal existing actionability rule because all three required
price-plan fields were absent. The risk/degraded, regime-sensitive and
news-heavy results included suggested-position language; the mixed-signal
result also addressed existing-position handling. Research must not make
position-sizing or account-allocation statements. These are material
role-boundary failures, not wording-only differences.

## Quality scorecard

`PASS` means the bounded manual comparison found no material regression.
`MINOR_DIFFERENCE` means conservative output with a non-disqualifying semantic
inconsistency. `FAIL` is a safety or role-boundary failure.

| Dimension | Result | Evidence |
| --- | --- | --- |
| Factual grounding | PASS, bounded | No confirmed unsupported material date/fact in the supplied evidence; not an external fact check |
| Date / temporal correctness | MINOR_DIFFERENCE | Some forward-looking reporting-status wording was not independently adjudicated |
| Risk and uncertainty coverage | PASS | All four new results contained an explicit risk warning |
| Data-quality awareness | PASS | The degraded context acknowledged missing/partial input |
| Thesis coherence | MINOR_DIFFERENCE | Regime output mixed bearish and not-yet-confirmed-bullish descriptions but resolved conservatively |
| Scenario / catalyst framing | PASS, bounded | News/risk and confirmation conditions were surfaced |
| Actionability discipline | **FAIL** | One BUY omitted all required price-plan geometry |
| Structured completeness | **FAIL for actionable result** | Generic structure passed, but the BUY plan was incomplete |
| Research-role discipline | **FAIL** | Repeated suggested-position / allocation content appeared |
| Usefulness to downstream Brain | **FAIL** | Malformed BUY and allocation language cannot be Brain-ready Research evidence |

No SELL/REDUCE enablement, broker command or canonical contract quantity was
observed. That does not cure the separate allocation-language breach.

## Performance and resource observations

| New context | Prompt / completion tokens | Load / generation | Decode tok/s | Result |
| --- | ---: | ---: | ---: | --- |
| Risk / degraded-data | 5,106 / 1,621 | 1.53 s / 136.50 s | 11.88 | WATCH / HOLD |
| Regime-sensitive | 6,184 / 1,763 | 1.28 s / 174.85 s | 10.08 | WATCH / HOLD |
| Technical conflict / actionable candidate | 5,918 / 1,804 | 0.57 s / 247.04 s | 7.30 | WATCH / HOLD |
| News-heavy | 6,616 / 1,759 | 0.64 s / 224.24 s | 7.84 | BUY / BUY, plan failure |

The four new runs had a 199.55 s median generation time (range 136.50–247.04
s). Including the two PR #21 runs gives a 162.70 s median across six
heterogeneous contexts. The original near-comparable PR #21 neutral result
remains the best speed evidence at about 29–31% faster than the historical
14B-6bit reference. The broader set is materially variable, includes a slower
247.04 s result, and does not establish a consistently strong production speed
advantage.

Each accepted replay was cold-loaded in a separate process-local window. No
swap increase was observed across individual completed windows; values declined
within each sampled window. This is bounded evidence, not a production
memory-pressure certification or an end-to-end HTTP equivalence claim.

## Why the candidate is not ready

1. A BUY was structurally parsed but lacked positive entry, stop and target.
2. Multiple outputs crossed Research's capital-allocation boundary with
   suggested-position wording.
3. Performance benefit was not consistent across the broader contexts.

No fail-closed guard was weakened to make the candidate pass. A future model
evaluation would need separately authorized, non-production proof of
Research-role discipline and complete actionable price plans under the frozen
prompt/parser contract. This report proposes no production change.

## Verification and closeout

- Focused non-production evaluation transport tests: `7 passed`.
- Candidate replays: 6 total assessed, 4 newly generated; cap of 8 respected.
- Production restoration: healthy `Qwen3-14B-MLX-6bit`, one loaded engine.
- Source changes in this PR: this documentation report only.
- Deployment: none.

Awaiting Architecture Review.
