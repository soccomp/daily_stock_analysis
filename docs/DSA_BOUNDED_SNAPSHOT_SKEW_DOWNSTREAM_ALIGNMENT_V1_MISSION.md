# DSA Bounded Snapshot Skew Downstream Alignment v1 — Mission

## Model Mode

- Model: **Terra**
- Reasoning: **High / 高**
- Why: this is a narrow DSA-only safety-semantic consistency fix. The architecture decision is already frozen below, so do not spend quota re-deriving the broader Single Brain design.

## Trigger / Evidence

PR #14 deployment proved the authoritative Athena Snapshot ingress is behaving correctly:

- deployed application SHA: `8755b40646b9e653b1edc226f5f3f42d0f839a6d`
- natural cycle: `m2-cycle-4e215f5f904995dc664801e5adf7506c18699a96`
- initial Snapshot: `+93.114 ms`, accepted
- post-research-final-refresh Snapshot: `+96.248 ms`, accepted
- approved producer-ahead skew budget: **1 second**, strict rejection only when `future_offset > 1s`
- Qwen research completed successfully in 212.07s
- downstream Brain-adjacent validation then rejected the same already-valid Snapshot because it still uses zero future tolerance
- no InvestmentDecision, mandate, dispatch, submission, or scorecard was persisted

This is a DSA validation-consistency bug, not evidence that Athena timestamps or the 1-second ingress budget should be changed.

## Architecture Decision — Frozen

The authoritative `PortfolioSnapshot` is allowed the same bounded producer-ahead tolerance throughout the DSA authority/Brain validation path.

The approved semantics are:

- `PortfolioSnapshot.as_of - reference_time <= 1 second` => may pass the future-time check, subject to all other authority/freshness/reconciliation/data-quality checks.
- `PortfolioSnapshot.as_of - reference_time > 1 second` => fail closed.
- Snapshot age > 300 seconds => fail closed exactly as today.

**Only the authoritative PortfolioSnapshot gets this infrastructure clock-skew allowance.**

Do NOT extend the tolerance to:

- ResearchBundle timestamps
- RiskPolicy effective times
- InvestmentDecision `created_at` / `valid_from` / `valid_until`
- execution timestamps
- broker timestamps generally

## Required Implementation Shape

Use one shared DSA-internal source of truth for the 1-second PortfolioSnapshot clock-skew budget.

Preferred minimal shape:

- a small internal authority/timing validation module or equivalent existing internal module;
- define the PortfolioSnapshot future-skew constant once;
- make M2 authority validation, `InvestmentShadowWiringService`, and `InvestmentDecisionEngine` consume the same semantics;
- preserving a class constant alias such as `M2ShadowLoopService.MAX_SNAPSHOT_CLOCK_SKEW` is acceptable for compatibility/tests, but its value must derive from the shared source rather than becoming a second policy definition.

Do not introduce a broad policy framework.

## Critical Non-Solution Constraints

Do **not** solve this by:

- changing the 1-second budget;
- changing 300-second freshness;
- replacing `now` with `max(now, snapshot.as_of)` to move decision timestamps into producer time;
- rewriting/clamping Snapshot `as_of` or `created_at`;
- changing Snapshot canonical JSON/content hash;
- adding an `accepted=true` flag to PortfolioSnapshot;
- putting infrastructure skew into RiskPolicy;
- putting skew into `DecisionSizingInput` or the InvestmentDecision contract;
- trusting ingress blindly and deleting downstream authority validation;
- changing Athena;
- changing scheduler cadence;
- tuning Qwen;
- changing execution behavior or permissions.

## Required Code Semantics

### M2 authority validation

Keep the existing exact semantics:

- future offset strictly greater than 1 second => `authoritative PortfolioSnapshot is future-dated` / canonical equivalent;
- exactly +1.000000s remains accepted;
- freshness remains 5 minutes / 300 seconds;
- reconciliation, simulation-only, account identity, UTC-awareness and data-quality gates remain unchanged.

Use the shared skew source of truth.

### Shadow Wiring

`InvestmentShadowWiringService._validate_inputs` currently rejects any `portfolio_snapshot.as_of > now`.

Change only the PortfolioSnapshot future check so:

- `portfolio_snapshot.as_of - now <= shared 1s budget` is accepted;
- `> shared 1s budget` is rejected;
- stale >300s remains rejected;
- RiskPolicy effective-time semantics remain unchanged.

Do not alter ResearchBundle construction timestamps or Decision validity timestamps.

### Investment Decision Engine

`InvestmentDecisionEngine._validate_authorities` currently combines Research and Portfolio future checks.

Split their semantics:

- Research remains zero-tolerance: `research.as_of > sizing.valid_from` must still reject.
- authoritative PortfolioSnapshot uses the shared 1-second bounded skew: `portfolio.as_of - sizing.valid_from > shared budget` rejects; <= budget may continue.

Do not add new Portfolio freshness semantics to the engine if it did not own them before this mission; freshness remains enforced by the existing upstream authority path.

All other Decision Engine validation and sizing semantics stay unchanged.

## Required Tests

Add/adjust focused deterministic tests proving at minimum:

1. **+93 ms / representative sub-second Snapshot** reaches Shadow Wiring and Decision Engine without future-time rejection.
2. **+1.000000s exact boundary** accepted by M2 authority validation, Shadow Wiring, and Decision Engine Portfolio checks.
3. **+1.000001s** fails closed at each relevant validation boundary.
4. **>300s stale Snapshot** still fails closed in the existing freshness-owning paths.
5. **ResearchBundle future timestamp remains zero-tolerance** in Decision Engine.
6. Snapshot `as_of`, `created_at`, canonical JSON and content hash are unchanged by the fix.
7. Existing RiskPolicy effective-time checks remain unchanged.
8. A focused Single Brain integration/recovery test demonstrates an already-ingress-accepted bounded-skew final Snapshot can proceed through Brain construction to a deterministic InvestmentDecision when all other inputs qualify.
9. No duplicate decision identity, mandate, dispatch, scorecard, or submission behavior is introduced.

Use existing fixtures where possible.

## Scope / Safety Boundaries

DSA only.

Do not modify:

- Athena source/runtime
- oMLX/Qwen config
- scheduler topology/cadence
- RiskPolicy schema or values
- PortfolioSnapshot contract fields/canonicalization
- Research inputs
- sizing/allocation formulas
- M3 execution coordinator semantics
- BUY/ADD/HOLD capability boundaries
- LIVE state
- SELL/REDUCE
- broker permissions
- auth/network exposure

`LIVE_TRADING=false` and simulation-only remain frozen.

## Validation / Quota Conservation

Run only the smallest sufficient validation:

1. focused timing/Shadow Wiring/Decision Engine tests;
2. focused M2/M3 Single Brain regression tests needed for authority/identity/execution safety;
3. Python compilation for changed modules;
4. `git diff --check`.

Do not run model benchmarks, Qwen generations, a soak, a forced scheduler cycle, or a broad full suite unless a focused regression exposes a reason that genuinely requires it.

## Acceptance

PASS only if all are true:

- one shared DSA source of truth represents the existing 1-second PortfolioSnapshot skew budget;
- ingress/M2, Shadow Wiring, and Decision Engine Portfolio validation agree on <=1s accepted / >1s rejected semantics;
- Research future validation remains zero-tolerance;
- 300s freshness remains unchanged;
- canonical Snapshot timestamps/content/hash remain untouched;
- RiskPolicy and decision-time semantics remain unchanged;
- no execution/trading authority expands;
- focused tests and relevant regressions pass;
- Draft PR opened against `athena-integration`;
- no merge and no deployment.

## ARCHITECTURE REVIEW GATE

STOP and report before implementation expansion if the fix appears to require:

- a PortfolioSnapshot contract change;
- a RiskPolicy change;
- a cross-repo Athena change;
- changing decision timestamps to producer time;
- changing the 1s/300s limits;
- changing Brain sizing/allocation;
- changing execution authority.

## AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine implementation/test issues are autonomous: imports, compatibility aliases, focused fixture updates, deterministic timing fixtures, type/compile issues, and ordinary branch/PR mechanics.

Resolve and continue without asking Owner to relay routine logs.

## Closeout

Post to the new Draft PR:

- exact base SHA
- exact head SHA
- changed files
- location of shared skew source of truth
- exact M2 / Shadow Wiring / Decision Engine semantics after change
- focused test counts/results
- relevant M2/M3 regression results
- compile / diff-check results
- confirmation Research remains zero-tolerance
- confirmation 1s / 300s / RiskPolicy / canonical Snapshot / execution boundaries unchanged
- confirmation no merge/deployment

Then STOP for ChatGPT Architecture Review.