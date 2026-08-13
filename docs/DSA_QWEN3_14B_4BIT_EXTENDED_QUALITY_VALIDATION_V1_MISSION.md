# DSA Qwen3-14B-4bit Extended Quality Validation v1 — Mission

## Model Mode

- Codex model: **Terra**
- Reasoning: **High / 高**
- Escalate to Sol only for a genuine Research/Brain authority, safety-contract, licensing, or production-isolation ambiguity.
- Conserve Codex quota. This is a bounded local evaluation, not architecture redesign.

## Canonical Context

- Repository: `soccomp/daily_stock_analysis`
- Governance base: `athena-integration@7ad55f9dfe8bc78314b8bb1fb0144ccb8d7c86e2` (PR #21 merge).
- Current approved M5 application runtime remains `8d538348d4ca9c4633a978f318faf9402119aaab` unless pre-existing drift is discovered.
- Production Research model remains `Qwen3-14B-MLX-6bit` through the existing loopback oMLX route.
- Candidate under evaluation is **only** `mlx-community/Qwen3-14B-4bit` at the already-downloaded pinned artifact revision used by PR #21.
- Do not evaluate Qwen3-8B-6bit again in this Mission. PR #21 already found an actionable BUY output with missing entry/stop/target and rejected that candidate under the existing fail-closed contract.
- PR #21 bounded A/B evidence for Qwen3-14B-4bit:
  - 2/2 returned candidate contexts passed the existing parser and integrity checker;
  - no repair was required;
  - neutral-case generation was about 150.55 s versus the historical 14B-6bit 211–219 s reference, roughly 29–31% faster;
  - candidate decode was about 11.6–12 tok/s versus historical ~8–10 tok/s;
  - no production model switch was authorized.
- Known oMLX launcher topology from PR #21: both `com.athena.olmx` and `homebrew.mxcl.omlx` may keep the production listener alive/respawned. The successful process-local isolation/rollback procedure from PR #21 is the preferred operational pattern; do not rediscover it unless local facts have changed.

## Owner Goal

Decide whether `Qwen3-14B-MLX-4bit` preserves DSA Research quality broadly enough to justify a **separate future production model-switch Mission**.

This Mission answers:

> Does moving from Qwen3-14B-6bit to the same 14B model class at 4-bit quantization introduce material Research-quality, structured-output, factual-grounding, or safety regressions across a broader representative evidence set?

This is **offline/local evaluation only**. It does not authorize production routing, deployment, scheduler changes, or trading changes.

## Architecture Boundary

Research may produce evidence, thesis, scenarios, uncertainty, data-quality assessment, structured actionability, and research price references.

Research must not receive or control:

- PortfolioSnapshot authority;
- account balances/positions for allocation purposes;
- RiskPolicy;
- target weights or quantities;
- broker actions;
- execution authority.

Brain remains the only capital-allocation authority. Athena remains execution/safety infrastructure. Do not weaken fail-closed validation to make the candidate pass.

## Frozen Candidate

Test exactly:

**`Qwen3-14B-MLX-4bit`**

using the same trusted/pinned artifact already downloaded for PR #21.

Do not:

- download another model;
- change model family;
- change quantization;
- test 8B again;
- tune temperature/top-p/top-k/max tokens merely to improve the candidate;
- shorten or rewrite the production Research prompt;
- change parser/schema/repair policy;
- enable thinking if production has `enable_thinking=false`.

The purpose is to validate the exact candidate under frozen DSA semantics.

## Phase A — Reuse Proven Isolation

Before generation:

1. verify no active production Research request;
2. capture current healthy production 14B-6bit oMLX state and both known launcher definitions;
3. verify the PR #21 process-local isolation sequence remains valid;
4. temporarily unload only the already-identified keep-alive launchd labels required to obtain a clean candidate window;
5. verify the production listener is absent before candidate load;
6. run candidate generation process-locally with no candidate HTTP route exposed to DSA;
7. restore the exact original launcher definitions and healthy 14B-6bit production service before the next natural Research window.

No DSA restart. No scheduler cadence/config change. No forced scheduler cycle.

If isolation facts differ from PR #21 in a way that makes rollback uncertain, stop at `QUALITY_VALIDATION_BLOCKED_BY_ISOLATION_DRIFT` rather than improvising.

## Phase B — Evaluation Set

Use **persisted Research-only contexts and repository-defined Research fixtures only**. No Bocha/search refresh, no cloud/paid model, no synthetic account state.

Build the smallest set that still covers the following semantic categories, targeting **6 completed candidate replays total** and never exceeding **8**:

1. **Neutral / watch-hold** — ordinary non-actionable Research.
2. **Bullish actionable-long** — a context/fixture where BUY/ADD is plausible and legal price-plan completeness can be evaluated.
3. **Risk / degraded-data** — missing, stale, conflicting, or low-quality evidence where uncertainty discipline matters.
4. **Regime-sensitive / market-structure** — context where broader market phase/structure should materially constrain interpretation.
5. **News-heavy / catalyst-risk** — persisted evidence containing multiple dated events or competing catalysts/risks.
6. **Technical conflict / mixed signal** — indicators disagree or price/technical evidence requires nuanced HOLD/WATCH rather than simplistic action.

If one category cannot be satisfied by a persisted context or existing repository fixture, document it as unavailable. Do not fabricate market facts.

### Baseline pairing

Prefer a persisted production 14B-6bit result for the same context when available.

Do **not** rerun 14B-6bit merely for symmetry unless the comparison would otherwise be invalid. At most **one** fresh 14B-6bit replay is allowed, and only if required to resolve a specific ambiguity; it counts toward the total replay cap of 8.

Exact action equality is not required. The candidate may differ semantically if its conclusion is grounded, contract-valid, and at least as risk-disciplined.

## Phase C — Structured Reliability Gates

For every returned candidate result, record:

- Analyzer success;
- parser success;
- schema validation;
- content-integrity result;
- bounded completion/repair count;
- missing required fields;
- normalized Research action;
- Research decision type / downstream semantic class where applicable.

### Hard rejection conditions

Any repeated material failure is disqualifying:

- parser/schema/integrity failure beyond the existing bounded repair path;
- missing required structured sections;
- ambiguous/unrecognized action;
- unsupported SELL/REDUCE treated as enabled capability;
- claimed account allocation/quantity/broker authority;
- hallucinated material facts or dates;
- suppression of known uncertainty/data-quality warnings.

## Phase D — Actionable-Long Quality Gate

At least **one completed context must exercise actionable-long validation** unless no repository/persisted fixture can do so without fabrication.

If candidate output is `buy` or `add`, require:

- positive entry;
- positive stop;
- positive target;
- `stop < entry < target`;
- no missing plan fields;
- rationale grounded in supplied evidence;
- no account quantity/target-weight decision inside Research.

If a bullish context legitimately yields HOLD/WATCH, do not coerce BUY. Score whether the non-actionable result is evidence-grounded and conservative.

One malformed BUY/ADD price plan in this broader validation is a serious regression. Two such failures automatically produce `QWEN3_14B_4BIT_NOT_READY`.

## Phase E — Factual / Research Quality Review

For each replay, compare the candidate against the persisted input evidence and, where available, the paired 14B-6bit result.

Score these dimensions as `PASS`, `MINOR_DIFFERENCE`, or `FAIL`:

1. factual grounding;
2. date/temporal correctness;
3. risk and uncertainty coverage;
4. data-quality awareness;
5. thesis coherence;
6. scenario/catalyst framing;
7. actionability discipline;
8. structured completeness;
9. Research-role discipline;
10. usefulness to downstream Brain consumption.

A different wording, confidence value, or HOLD/WATCH choice is not itself a failure. Focus on semantic quality and safety.

## Phase F — Performance / Resource Confirmation

This Mission is primarily a quality validation, but retain performance evidence for each replay:

- prompt tokens;
- completion tokens;
- model load time;
- generation wall time;
- decode tok/s when observable;
- memory pressure and swap delta before/after the controlled window;
- cold/warm status.

Do not claim end-to-end equivalence to production HTTP/oMLX unless transport/retry mechanics are truly comparable.

### Performance interpretation

The prior A/B showed roughly 29–31% neutral-case generation improvement. For production consideration, this broader run should show that the gain is **not a one-off**.

Use this combined rule for a future switch recommendation:

- quality must pass strongly across the broader set; and
- comparable candidate generation should generally remain **>=25% faster** than the existing 14B-6bit historical reference where comparison is valid, **or** save at least ~50 seconds on the current multi-minute Research workload; and
- no material memory/swap regression may appear.

This does not guarantee production approval; it only determines whether a separate production-switch Mission is justified.

## Final Verdict Categories

Choose exactly one:

### `QWEN3_14B_4BIT_READY_FOR_SWITCH_MISSION`
Use only if the candidate passes the broader Research-quality/safety gates strongly and the observed speed/resource benefit remains material enough to justify a separately reviewed production-switch Mission.

### `QWEN3_14B_4BIT_PROMISING_NEEDS_MORE_EVIDENCE`
Use if quality is mostly strong but the available contexts are insufficient, actionable-long evidence is missing, or performance comparability remains too weak for a switch decision.

### `QWEN3_14B_4BIT_NOT_READY`
Use if material structured, factual, risk, actionable-plan, or role-discipline regressions appear, or the speed/resource gain does not justify the quality risk.

### `QUALITY_VALIDATION_BLOCKED_BY_ISOLATION_DRIFT`
Use only if the previously proven isolation/rollback mechanism no longer works safely and resolving it would cross the Mission boundaries.

## Required Owner Answer

The report must state plainly:

- exact candidate artifact + pinned revision;
- exact number and categories of completed replays;
- parser/schema/integrity pass rate;
- repair count/rate;
- whether actionable BUY/ADD was exercised;
- if actionable, whether all price plans were legal and complete;
- number of factual-grounding/risk-discipline failures;
- most important semantic differences versus 14B-6bit;
- median/representative candidate generation time and decode throughput;
- realistic speed improvement versus current 14B-6bit evidence;
- memory/swap observation;
- **14B-4bit 的 Research 质量是否足够替代 14B-6bit：是 / 暂时不能确认 / 否**;
- **是否建议进入生产模型切换 Mission：是 / 否**.

## Safety / Frozen Boundaries

No changes to:

- DSA production `src/`;
- Research prompt/schema/parser/repair policy;
- production model route;
- DSA `.env` or runtime configuration;
- scheduler cadence/topology;
- PortfolioSnapshot freshness/skew/authority;
- RiskPolicy;
- Brain sizing/allocation;
- Athena;
- execution/idempotency/reconciliation;
- broker/account/manual-ledger state;
- LIVE state;
- BUY/ADD/HOLD/SELL/REDUCE capability boundary.

No cloud/paid model call. No Bocha/search refresh. No trading mutation. No secret exposure.

## Deliverable

Create a dedicated branch from the current canonical `athena-integration` governance head.

Deliver one report:

`docs/DSA_QWEN3_14B_4BIT_EXTENDED_QUALITY_VALIDATION_V1_REPORT.md`

Optional non-production helper changes under `tools/` plus focused tests are allowed only if needed for reproducibility. No production `src/` change is expected.

Open a **Draft PR** to `athena-integration` containing:

- exact base/head SHA;
- isolation/rollback evidence;
- context-category inventory;
- exact replay count;
- structured-reliability scorecard;
- factual/Research-quality scorecard;
- actionable-long evidence;
- performance/resource scorecard;
- final verdict;
- plain-language Owner answer;
- confirmation production 14B-6bit was restored healthy;
- confirmation of zero DSA/Athena/trading mutation.

Stop at:

`ARCHITECTURE REVIEW GATE — QWEN3_14B_4BIT_EXTENDED_QUALITY_VALIDATION_V1_READY`

No merge. No deployment. No production model switch.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine persisted-context discovery, fixture selection, process-local candidate execution, launcher unload/reload using the already-proven topology, parser/integrity checks, semantic comparison, telemetry collection, and report generation are autonomous within the hard limits above.

## OWNER HARD STOP

Stop before continuing if it would require:

- production model routing to 4bit;
- DSA restart;
- scheduler cadence/config change;
- paid/cloud inference;
- new model download or different candidate;
- production Prompt/Schema/Research semantic change;
- Research/Brain/RiskPolicy authority change;
- auth/network weakening;
- more than 8 total new full model replays;
- destructive removal of the production 14B-6bit model;
- broker/account/trading mutation;
- LIVE or SELL/REDUCE enablement;
- secret exposure.