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

## Fix Implementation — 2026-08-15 final runtime closure

### Changes

- Replaced the mixed handoff/execution status check with an explicit durable
  Athena acknowledgement contract. DSA now records proposal ID, proposal hash,
  acknowledgement ID/state, lifecycle state and deduplication state.
- All legal Athena lifecycle states (`ACCEPTED`, `NO_ACTION`, `ALLOCATED`,
  `BLOCKED`, `BLOCKED_PRE_SUBMISSION`, `PENDING_RECONCILIATION`, `REJECTED`,
  `FILLED`) are valid after `acknowledgement_state=ACCEPTED` and do not convert a
  successful proposal delivery into `FAILED_CLOSED`.
- A missing POST response triggers one read-only acknowledgement lookup by
  proposal ID. The publisher never repeats the POST, preserving Athena
  idempotency when the server persisted the proposal before the client timeout.
- DSA remains research/proposal-only. No final allocation, quantity, mandate,
  execution permission or Worker credential was added.

### Validation

- Focused contract tests cover every legal lifecycle state and POST-timeout ACK
  lookup with exactly one POST. The complete Issue-related DSA matrix passed
  `167 passed, 1 skipped`; the skip and five warnings are pre-existing optional
  dependency/test-collection conditions.
- The 2026-08-15 recurring runtime selected `000977:BOTH`, produced report 132
  with a HOLD/55 result, received durable ACK
  `athena-ack-5cadf095d2c990cfb5a51735c9c9da43`, and ended
  `COMPLETED persisted=1`. Athena independently advanced proposal
  `proposal-241fbd89aaa01130ce6f325f44533018` to `NO_ACTION`; no Worker submit
  occurred.

### Risks and rollback

- Athena versions that do not expose the durable ACK contract now fail closed;
  silently accepting the former ambiguous status response would recreate the
  audited split-brain acknowledgement bug.
- Roll back this follow-up commit in both repositories together. Rolling back
  only DSA would make current Athena acknowledgements appear invalid again.
