# Single Brain Architecture Constitution

**Version:** 1.0

**Adopted:** 2026-08-08

**Status:** Normative

This document is the cross-repository authority boundary for DSA and Athena. An implementation, legacy path, test fixture, runtime convention, or later document that conflicts with it is non-authoritative until this constitution is explicitly amended in coordinated pull requests.

## 1. System laws

The combined system has exactly one investment brain, one final investment decision, and one outcome scorecard lineage.

- **Single Brain:** DSA Brain alone decides what an account should become.
- **Single Decision:** `InvestmentDecision` is the only final investment decision. UI projections, research opinions, risk discoveries, and execution states are not additional decisions.
- **Single Scorecard:** research, decision, mandate, execution, reconciliation, and outcome must remain reconstructable through one `decision_id` lineage. P0 establishes the lineage; a complete scorecard UI is a later phase.

## 2. Authority map

| Concern | Authority | Required boundary |
| --- | --- | --- |
| Market and asset research | DSA Research | Describes evidence, thesis, uncertainty, and invalidation; never final allocation or execution quantity. |
| Investment decision | DSA Brain | Chooses action, target, delta, entry, stop, take profit, validity, and final quantity. |
| Risk policy | Explicit owner/system policy | Constrains DSA Brain during capital allocation; is not a second execution-time investment opinion. |
| Actual account and portfolio truth | Athena runtime / broker reconciliation | Produces authoritative, immutable `PortfolioSnapshot` observations. |
| Execution | Athena Trading Spine | Executes the mandate exactly or returns a non-executing terminal/safety state. |
| Human-readable decision view | DSA `DecisionSignal` projection | Derived from the same `InvestmentDecision`; never an execution protocol or second engine. |

For an Athena-integrated account, DSA may persist or display an immutable mirror only when it is marked `source = ATHENA_RUNTIME`, `authoritative = true`, and `read_only = true`. DSA must not maintain a second authoritative portfolio ledger.

## 3. Canonical contracts

The cross-layer protocol consists of six versioned contracts:

1. `ResearchBundle`
2. `PortfolioSnapshot`
3. `RiskPolicy`
4. `InvestmentDecision`
5. `ExecutionMandate`
6. `ExecutionResult`

Published contract objects are strictly validated and immutable. State changes create new objects. Canonical timestamps are timezone-aware, canonical monetary/price/weight values use decimal strings, and canonical JSON is stable and content-hashed. IDs, hashes, producer provenance, `trace_id`, supersession, and `decision_id` lineage must not be discarded at repository boundaries.

## 4. Decision and execution boundary

DSA Brain must place the final quantity in `InvestmentDecision`. `ExecutionMandate` is a deterministic, non-LLM projection from that decision, and its quantity must equal the decision delta.

Athena may either:

1. submit exactly the mandated quantity, or
2. submit zero and return `BLOCKED`, `EXPIRED`, `BROKER_REJECTED`, or `UNKNOWN` as appropriate.

Athena must never resize, round, reallocate, alter target weight, change the action, or invoke research/LLM/screening/position-sizing logic. If lot size, cash, position, account state, or the referenced portfolio snapshot no longer matches, Athena blocks and returns the latest observed portfolio truth. DSA must make any replacement decision.

## 5. Execution safety and uncertainty

Athena's safety kernel is operational, not investment-advisory. It may validate schema, hashes, validity windows, simulation-only mode, `LIVE_TRADING == false`, account identity, idempotency, duplicate/conflicting orders, market/contract/lot/price authorization, runtime availability, snapshot freshness, and submission integrity.

The new vertical slice is simulation-only. No constitution change or implementation PR may silently enable live trading.

`UNKNOWN` is a first-class state. An unknown submission must not be retried automatically; reconciliation must establish broker/runtime truth first. A partially filled order may continue only as the same active broker order. After cancellation or expiry, Athena must not resubmit the remainder without a new DSA decision and mandate.

## 6. Fail-closed rule

Missing or unverifiable critical fields, policy, authoritative portfolio truth, hashes, broker status, or reconciliation evidence must not be guessed. Failure to prove that an exact authorized submission is safe results in zero submission or `UNKNOWN` followed by reconciliation. Execution errors never authorize a changed investment decision.

## 7. Dependency boundary

- DSA Research must not depend on broker SDKs, order submission, or execution engines.
- DSA Decision must not depend on broker submission or worker implementations.
- Athena Trading Spine must not depend on LLMs, research, screening, decision agents, portfolio allocation, or position-sizing algorithms.
- Legacy paths may coexist during additive migration, but a DSA mandate must bypass any legacy Athena investment judgment or sizing path.

## 8. Governance and canonical handoff

This constitution and each repository's `SINGLE_BRAIN_P0_IMPLEMENTATION_STATUS.md` are the canonical written handoff. GitHub pull requests that modify them are the canonical review, evidence, and change history for future phases.

Future phases must:

- update the affected status document in the same PR as the implementation;
- use coordinated, cross-linked PRs when a contract or authority boundary changes across repositories;
- state compatibility, test evidence, migrations, and known gaps in the PR;
- preserve the six-contract wire compatibility or version it explicitly; and
- amend this constitution in both repositories when an authority rule changes.

Issues, chat summaries, READMEs, and informal handoff notes may provide context, but they do not supersede these documents or their PR history.
