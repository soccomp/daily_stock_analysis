# Issue #9 implementation analysis

- Authority conflict found: the former M3 path read a portfolio snapshot and
  RiskPolicy in DSA, calculated final target/delta quantity, and projected an
  ExecutionMandate.
- Required correction: preserve DSA research authority, introduce canonical
  advisory `InvestmentProposal`, and terminate normal DSA runtime at the Athena
  loopback handoff.
- Compatibility: retain old contracts/repositories for historical reads and
  isolated tests, but fail closed if runtime requests `SIMULATION_EXECUTION`.
- Verification: canonical/hash tests, authority-field exclusion, scheduler
  mode test, Athena cross-contract tests, HOLD no-action runtime validation,
  and simulation-only enforcement.

## Fix Implementation — 2026-08-14 independent-audit follow-up

### Changes

- Removed the proposal-only `DSA_SINGLE_BRAIN_PROPOSAL_SYMBOLS` configuration.
- Extracted the established M2 holdings-first selector into
  `src/investment/m2/selection.py` and reused it from both M2 shadow and Issue
  #9 proposal handoff.
- Proposal handoff now captures the canonical read-only Athena
  `PortfolioSnapshot`, combines positive CN holdings with the existing M2
  allowlist, preserves de-duplication and configured limits, and records the
  `HOLDING`/`ALLOWLIST`/`BOTH` research reason.
- DSA remains advisory-only: no portfolio policy, final quantity, mandate,
  broker, order, or fill authority was added.

### Validation

- Related DSA suite: `127 passed, 2 skipped` across proposal, M2, historical
  M3 compatibility, canary, scheduler, ingress, resilience, readiness, and
  runtime-explainability tests.
- Focused regression proves a holding/allowlist overlap is `BOTH`, a second
  allowlisted name is `ALLOWLIST`, ordering is holdings-first, duplicates are
  removed, the global maximum is applied, and repeated cycles are
  deterministic.
- Runtime acceptance evidence is recorded in the final GitHub Issue #9 report;
  no synthetic fill is represented as a factual broker fill.
- Restarted runtime factual cycle selected `000977:BOTH`; source report `121`
  completed as `观望`/HOLD with score `63`, and Athena durably recorded
  `proposal-db72672238cded09e70961d8a6c48d6d` as `NO_ACTION` with no mandate,
  order or fill. The DSA caller summary still ended `FAILED_CLOSED persisted=0`,
  so its acknowledgement projection is reported as a remaining trace break.

### Risks and rollback

- If the canonical Athena snapshot endpoint is unavailable or the combined
  selector is empty, the proposal cycle fails closed before analysis or
  publication.
- Rollback is the single follow-up commit for this audit. Reintroducing a
  proposal-only symbol universe is intentionally not a supported rollback
  because it recreates the audited authority/selection regression.
