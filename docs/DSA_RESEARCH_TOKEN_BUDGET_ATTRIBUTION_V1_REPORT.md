# DSA Research Token Budget Attribution v1 — Read-only Report

## Scope and safety result

This is a read-only attribution and design review of the current local-Qwen
Research path. It did not invoke Qwen, Bocha, a cloud model, or any search
provider. It did not change production source, Prompt, Schema, model,
quantization, oMLX configuration, scheduler, Athena, RiskPolicy, or execution
behavior.

The observation set is the newest ten completed, comparable local
`Qwen3-14B-MLX-6bit` Research records available at review time. Identifiers,
symbols, account facts, news bodies, and all prompt bodies are intentionally
omitted. Counts below are sanitized aggregates only.

## Method

1. Read the persisted `AnalysisHistory` result/context snapshots in read-only
   mode and the local oMLX completion telemetry already written for the same
   ten completed Research requests.
2. Trace the production assembly path:
   `AnalysisPipeline` enriches the context, adds market phase/daily-market/
   market-structure inputs, renders `AnalysisContextPack`, then calls
   `GeminiAnalyzer.analyze`; `GeminiAnalyzer._get_analysis_system_prompt` and
   `_format_prompt` build the final system and user messages.
3. Re-render only the persistable prompt components locally, without calling a
   model. Token counts use the deployed Qwen tokenizer artifact
   (`tokenizer.json`, vocabulary size 151,669). oMLX telemetry remains the
   source of truth for each request's total input tokens, completion tokens,
   and wall time.

The market-phase raw object is deliberately runtime-only and is not persisted.
The residual between reconstructed content and oMLX input telemetry therefore
contains the chat envelope plus this non-persisted phase rendering. It is
reported as residual rather than guessed into another category. The rendered
AnalysisContextPack summary was reconstructed from the persisted low-sensitivity
overview; its token count is exact for that reconstruction and is separately
labelled below.

## Sample-level historical telemetry

| Sanitized sample | Input tokens | Completion tokens | Wall time (s) |
|---|---:|---:|---:|
| S01 | 7,197 | 1,751 | 197.73 |
| S02 | 7,001 | 1,966 | 212.67 |
| S03 | 7,001 | 1,736 | 193.98 |
| S04 | 6,812 | 1,776 | 210.83 |
| S05 | 6,930 | 1,726 | 187.23 |
| S06 | 6,930 | 1,669 | 299.53 |
| S07 | 6,972 | 1,839 | 225.95 |
| S08 | 7,052 | 1,711 | 331.03 |
| S09 | 7,069 | 1,725 | 211.76 |
| S10 | 5,754 | 1,486 | 157.13 |
| **Median** | **6,986.5** | **1,731** | **211.30** |
| Mean | 6,871.8 | 1,738.5 | 222.79 |

These are initial Research requests. Where historic bounded-completion repair
occurred, its additional request is not conflated with the initial prompt
budget; repair is an output-validity path, not an input-context component.

## Prompt attribution

The following are tokenizer counts of independently re-rendered components.
They are *marginal* counts: prompt sections interact at token boundaries, so
they must not be summed as a second total. Percentages use the 6,986.5-token
telemetry median and are directional only.

| Rank | Component | Median tokens | Share of median input | Classification | Evidence / boundary |
|---|---|---:|---:|---|---|
| 1 | System role, doctrine, market guidelines, activated skill policy and action constraints | 2,963 | 42.4% | `MUST_RETAIN_EXACT_SEMANTICS` | Defines factual grounding, strategy discipline, and decision/action language. |
| 2 | News/search evidence block | 1,520 | 21.8% | `BOUNDED_CONTEXT_CANDIDATE` | Largest variable block; dates, source evidence, risk/catalyst coverage and recency rules are semantic requirements. |
| 3 | User task, JSON/dashboard instructions, taxonomy and output-format constraints | 1,084 | 15.5% | `MUST_RETAIN_EXACT_SEMANTICS` | Required for structured AnalysisResult and downstream actionability extraction. |
| 4 | Realtime/technical/chip/trend and yesterday comparison | 457 | 6.5% | `MUST_RETAIN_EXACT_SEMANTICS` | Direct research facts; observed range 455–547 tokens. |
| 5 | Daily-market and market-structure context | 407 | 5.8% | `BOUNDED_CONTEXT_CANDIDATE` | Useful market regime/structure facts; observed range 331–491 tokens. |
| 6 | AnalysisContextPack rendered status summary | 269 | 3.8% | `STRUCTURAL_COMPRESSION_CANDIDATE` | Status/warning information overlaps in part with detailed factual blocks, but no removal is proven safe yet. |
| 7 | Current quote values over the fixed user template | 54 | 0.8% | `MUST_RETAIN_EXACT_SEMANTICS` | Small and directly factual. |
| — | Chat framing plus non-persisted market-phase rendering residual | 134 | 1.9% | `UNKNOWN_NEEDS_SEMANTIC_REVIEW` | 134–224 observed; retained as an honest attribution residual. |

The reconstructed user message median is 3,880 tokens; the fixed user-template
portion is 1,084 tokens. Combined with the 2,963-token system message, the
fixed semantic contract is already approximately 4,047 tokens before current
news and dynamic market evidence. This is why a safe context-only change cannot
be assumed to remove 20% without reviewing the evidence-bearing blocks.

### Prompt trace and repeated information

- System instruction builds market role/guidelines and active skill policy in
  `src/analyzer.py:_get_analysis_system_prompt`.
- The user message adds phase, daily-market, market-structure and pack summary,
  then technical/realtime/fundamental/capital/chip/trend/news facts and the
  output task in `src/analyzer.py:_format_prompt`.
- `src/core/pipeline.py:_build_analysis_context_pack_outputs` renders a compact
  status summary from pipeline artifacts before the Analyzer is called.

No fully duplicated evidence block is proven from this read-only sample. The
only plausible overlap is the compact AnalysisContextPack status summary with
the presence/quality signals already visible in detailed sections. That is a
candidate for a future controlled semantic test, not approval to delete it.

## Latency attribution

The median completion is 1,731 tokens and median wall time is 211.30 seconds.
Historical oMLX telemetry records end-to-end completion timing but does not
separately expose prefill time for each request. Accordingly:

- input shortening can reduce prefill/context memory pressure;
- it cannot be credited with the full 211-second wall time, because completion
  decoding is substantial (historical effective output throughput is roughly
  8–10 tokens/s);
- an input-only saving has no evidenced lower bound above zero from this data;
  a conservative planning range for a 10–15% input reduction is **0–25 seconds
  per request**, pending an offline or controlled serving-layer measurement;
- no claim of a 60-second saving is justified by the available telemetry.

## Future optimization packages (not implemented)

### P1 — News evidence budget with semantic coverage checks

Constrain only the *selection/packing* of news evidence to a deterministic,
source/date-preserving budget. Preserve every currently required category
(risk alert, catalyst, earnings expectation and dated latest news), recency
rule and provenance reference. This targets the 1,520-token median news block.

- Candidate reduction: 10–15% of total input only after coverage tests prove
  that no required dated evidence is lost.
- Classification: `BOUNDED_CONTEXT_CANDIDATE`.
- Required proof before implementation: historical prompt diff plus structured
  AnalysisResult/actionability parity; no production Prompt wording change in
  this package.

### P2 — AnalysisContextPack structural deduplication experiment

Test whether status-only warnings that are already represented by detailed
facts can be represented once while preserving all data-quality signals.

- Candidate reduction: up to the 269-token median pack section (3.8%).
- Classification: `STRUCTURAL_COMPRESSION_CANDIDATE`.
- Required proof before implementation: degraded-data cases must preserve the
  same confidence and fail-closed Research/Brain behavior.

### P3 — Market context bounded representation

Evaluate a fixed, deterministic representation for daily-market and
market-structure context, preserving phase/regime, breadth, support/resistance
and warning semantics.

- Candidate reduction: a portion of the 407-token median context section.
- Classification: `BOUNDED_CONTEXT_CANDIDATE`.
- Required proof before implementation: regime-sensitive historical cases must
  retain the same structured action and rationale obligations.

None of P1–P3 may alter RiskPolicy, InvestmentDecision authority, canonical
contracts, execution, Athena, scheduler cadence, or the local model.

## Required verdict

**Verdict: `CONTEXT_OPTIMIZATION_SUPPORTING_ONLY`.**

There is useful context-budget work, especially in dated news packing, but the
read-only evidence does not prove a safe 20% reduction or a 60-second latency
reduction. The dominant fixed system and structured-output contract must remain
exact, while completion decoding remains a material part of observed latency.

- **可证明的重复/可压缩份额：** no full block is proven duplicative; the
  structural candidate is at most 3.8% today. News is a bounded-context
  candidate, not proven duplication.
- **最安全的可行缩减：** 3–4% (P2 only), subject to a semantic regression
  proof. A 10–15% total reduction is a P1 design target, not a current result.
- **方案 1 能不能单独解决慢：** 只能部分改善。It may reduce prefill and
  memory pressure, but cannot remove output decoding time.
- **继续方案 2 lightweight A/B：** 是。方案 1 只能部分降低 prefill/context
  压力，不能解决主要的 completion decode / model-speed 瓶颈；下一步应继续
  进行轻量的本地模型 A/B。P1/P2 仍须先完成各自的语义保真设计与评审，且本结论
  不授权付费云模型 A/B。

## Non-changes and review boundary

This report changes documentation only. It makes no recommendation to loosen
the one-second snapshot skew boundary, the 300-second freshness boundary,
Research/Brain/Execution authority, local oMLX configuration, or any trading
permission. A future implementation of any package above requires a separate
architecture review and focused semantic regression plan.
