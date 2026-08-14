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
