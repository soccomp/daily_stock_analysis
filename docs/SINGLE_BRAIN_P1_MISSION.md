# Single Brain P1 Mission

**Version:** 1.0

**Adopted:** 2026-08-08

**Mission status:** COMPLETE — READY FOR ARCHITECTURE REVIEW

**Normative parent:** [Single Brain Architecture Constitution](SINGLE_BRAIN_CONSTITUTION.md)

This document is the canonical cross-repository mission authority for P1. The
same version must exist in the DSA and Athena P1 branches. Repository code,
tests, implementation-status documents, and the two cross-linked Draft P1 pull
requests provide the implementation evidence.

If this mission conflicts with the Single Brain Constitution, the Constitution
wins and implementation must stop. P1 does not amend the Constitution or any
authority boundary.

## 1. Mission outcome

P1 extends the accepted P1A analysis shadow into one simulation-only vertical
canary and one persistent, read-only decision scorecard:

    real completed DSA AnalysisResult
      -> ResearchBundle
      -> authoritative Athena PortfolioSnapshot A
      -> explicit RiskPolicy
      -> DSA InvestmentDecision
      -> DecisionSignal
      -> canonical ExecutionMandate
      -> Athena Trading Spine
      -> observed simulated execution
      -> ExecutionResult
      -> reconciled authoritative PortfolioSnapshot B
      -> DSA Single Decision Scorecard

P1 remains one account, one explicitly allowlisted CN equity, one BUY/ADD/HOLD
decision, one LIMIT mandate, and simulation only.

## 2. Authority and dependency rules

- DSA Research describes the asset and never allocates capital.
- DSA Brain alone calculates target weight, final target quantity, and delta
  quantity.
- Athena alone owns observed/reconciled account truth and execution safety.
- Athena submits the exact mandate quantity or submits zero.
- DSA never imports Athena implementation modules, broker SDKs, worker
  implementations, or Trading Spine internals into Research or Decision.
- Athena Trading Spine never imports research, LLM, screening, decision-agent,
  allocation, target-weight, or position-sizing logic.
- Cross-repository transport must use canonical contract JSON without changing
  IDs, hashes, Decimal strings, timestamps, or lineage.
- DSA may persist immutable portfolio mirrors for lineage, but never an
  authoritative account ledger.
- The scorecard is observational and cannot decide, mandate, submit, retry,
  reconcile, or mutate account truth.

## 3. P1B — Simulation Canary

### 3.1 Brain-owned sizing

Before a mandate can be emitted, DSA calculates:

    stop_loss_fraction = (entry_limit - stop_price) / entry_limit
    risk_target_weight = risk_budget_per_trade / stop_loss_fraction
    proposed_target_weight = min(
        risk_target_weight,
        max_single_position_weight,
    )

All calculations use exact Decimal semantics. max_single_position_weight is a
cap, not a target. No confidence-based discretionary sizing is permitted. The
existing DSA InvestmentDecisionEngine must still enforce current position, max
single position, total exposure, minimum cash, concurrent positions, lot
rules, stop-risk budget, and every applicable RiskPolicy constraint. An
existing position at or above the risk-derived target produces HOLD in the P1
BUY/ADD-only scope.

### 3.2 Canary boundary

- P1A shadow and P1B canary have separate feature flags; both default OFF.
- Enabling P1A does not enable P1B.
- The canary requires a simulation-only account, LIVE_TRADING exactly false,
  one configured account, an explicit symbol allowlist, CN equity identity,
  BUY/ADD/HOLD, LIMIT, and a canonical mandate.
- P1 provides a development-worktree one-shot path. It does not modify or
  silently enable any deployed launchd service or plist.
- No live worker, live broker, SELL/REDUCE, automatic stop, automatic
  take-profit, scheduler redesign, queue, service discovery, distributed
  infrastructure, repository merge, or new database platform is permitted.

### 3.3 Execution and uncertainty

- mandate.quantity equals decision.delta_quantity.
- Athena may submit exactly that quantity or zero, never another quantity.
- Athena does not round, resize, reallocate, or make an investment judgment.
- Invalid lot and stale/changed account truth are blocked. Changed truth
  returns fresh observed truth for a new DSA decision.
- UNKNOWN is first-class and never causes automatic submission retry.
- Durable intent/idempotency and broker identity must survive restart.
- A partial ACTIVE order may continue only as the same order.
- Cancelled or expired remainder requires a new DSA decision.
- Snapshot A and Snapshot B both originate from Athena observed/reconciled
  runtime state. Snapshot B is never inferred from expected fills.

### 3.4 P1B acceptance

Focused and cross-repository tests must prove:

- a real completed DSA analysis produces the canonical research/decision chain;
- risk-budget sizing is deterministic and positions at/above target HOLD;
- exact mandate quantity reaches Athena unchanged, or Athena submits zero;
- Snapshot B quantity equals Snapshot A plus observed filled quantity;
- UNKNOWN does not submit a second order;
- restart does not duplicate submission;
- default-off configuration has zero execution side effects;
- non-allowlisted symbols submit zero; and
- any environment where LIVE_TRADING is not exactly false fails closed.

## 4. P1C — Minimal Single Decision Scorecard

DSA persists one read-only scorecard lineage keyed by decision_id. It
reconstructs:

- ResearchBundle and research references;
- authoritative PortfolioSnapshot A mirror;
- RiskPolicy ID and version;
- InvestmentDecision;
- DecisionSignal;
- ExecutionMandate;
- ExecutionResult history; and
- authoritative PortfolioSnapshot B mirror.

Immediate diagnostics include requested, submitted, filled, and remaining
quantity; average fill; fees; slippage; execution state; and reconciliation
state when available.

The scorecard answers why the Brain decided, what account truth and policy it
saw, what was authorized and submitted, what filled, and what the authoritative
account became. It does not invent long-term performance scoring. Future
1/5/20-day evaluation is outside P1.

P1C must reuse existing DSA persistence and API/service conventions. Retrieval
is read-only and additive. Unrelated public behavior remains unchanged.

## 5. Phase and publication gates

The two P1 branches are stacked on the accepted heads:

- DSA base: codex/p1a-shadow-wiring
- Athena base: codex/p0-trading-spine

Each repository uses one Draft P1 pull request. The PRs remain unmerged and are
cross-linked. Commits are separated into:

1. P1 Mission governance;
2. P1B;
3. P1C where the repository is affected; and
4. P1 closeout.

After each implementation phase, focused tests must pass, implementation-status
documents must be updated, and the phase must be committed before continuing.

Final closeout requires full DSA and Athena regression, focused
cross-repository P1 tests, wire-compatibility and dependency-boundary tests,
proof that default configuration executes nothing, proof that no live-trading
path was enabled, final status/mission updates, and cross-linked unmerged Draft
PRs.

## 6. Hard-stop rules

Implementation must stop before proceeding if any condition is true:

1. The Constitution or an authority boundary must change.
2. Live trading must be enabled.
3. A destructive data migration or deletion is required.
4. A deployed launchd/runtime configuration must change.
5. Exact-quantity execution cannot be guaranteed.
6. UNKNOWN would require blind retry.
7. A second authoritative portfolio ledger is required.
8. A second investment decision or sizing authority is required.
9. Sensitive credentials or data risk exposure to a public repository.
10. Athena mainline/runtime-baseline promotion becomes necessary.
11. Full regression cannot be restored without unrelated product behavior
    changes.
12. Two materially different product or architecture choices require owner
    preference.

Routine file placement, naming, helper APIs, tests, in-scope refactoring,
introduced bug fixes, documentation, and mechanically safe stacked-branch
maintenance are not hard stops.

## 7. Out of scope and completion marker

P1 does not add SELL/REDUCE, live execution, multi-symbol allocation, automatic
stops/take-profit, broad UI redesign, scheduler consolidation, long-term
outcome scoring, distributed coordination, or legacy retirement.

When every closeout gate passes, both copies of this document must be updated
to Mission status: COMPLETE — READY FOR ARCHITECTURE REVIEW, with exact test
evidence, P1 PR links, compatibility notes, and known gaps.

## 8. Completion record

P1A, P1B, P1C, and the P1 governance/regression closeout are complete on the
two unmerged Draft P1 branches. The Single Brain Constitution and every
authority boundary remain unchanged.

### 8.1 Canonical Draft PRs

- DSA: https://github.com/soccomp/daily_stock_analysis/pull/3, stacked on
  `codex/p1a-shadow-wiring`.
- Athena: https://github.com/soccomp/athena/pull/2, stacked on
  `codex/p0-trading-spine`.

The PRs are cross-linked, Draft, and intentionally unmerged pending
architecture acceptance.

### 8.2 Final verification evidence

- DSA required backend gate: **5793 passed, 4 deselected, 501 subtests
  passed**; syntax, critical flake8, deterministic checks, and the offline
  suite all passed.
- Athena full regression: **883 passed**.
- DSA P0/P1 contract, architecture, cross-repository canary, and scorecard
  suite: **53 passed**.
- DSA P1C plus storage/config/canary focused suite: **108 passed**.
- Athena P0/P1 Trading Spine focused suite: **45 passed**.
- Canonical PortfolioSnapshot, ExecutionMandate, and ExecutionResult wire
  round trips, hashes, Decimal strings, IDs, timestamps, and lineage passed.
- Architecture guards passed: DSA Research/Decision remain independent from
  Athena/broker submission; Athena Trading Spine remains independent from
  Research/LLM/Decision/allocation/sizing; the scorecard remains observational.
- Default DSA configuration keeps P1A shadow and P1B execution OFF. The canary
  tests prove zero submission while disabled or non-allowlisted, fail closed
  unless LIVE_TRADING is exactly false, exact quantity or zero, UNKNOWN no
  automatic retry, durable restart deduplication, and observed Snapshot B.
- No live trading, live worker, live broker, launchd service, plist, deployed
  configuration, or public audit-snapshot repository was changed or enabled.

### 8.3 Compatibility and known gaps

- Existing DSA and Athena product paths, public behavior, legacy investment
  flows, and simulation-only guarantees remain additive and compatible.
- The P1 canary is a development-worktree, same-host, single-account,
  allowlisted CN-equity BUY/ADD/HOLD LIMIT slice; deployed/Windows-worker and
  live-broker integration remain out of scope.
- The P1 scorecard is an immutable immediate lineage record. Mutable lifecycle
  revisions, broad UI work, and 1/5/20-day outcome evaluation remain out of
  scope.
- Distributed multi-process coordination, multi-symbol allocation,
  SELL/REDUCE, automated stops/take-profit, scheduler consolidation, and
  legacy retirement remain future separately governed phases.
