# Issue #9 Authority Boundary

Issue #9 supersedes the former M3 authority statement for all current runtime
decisions. DSA is authoritative for market/universe analysis, screening,
research, thesis, action, confidence, expected return, price plan and an
optional advisory target-weight suggestion.

The normal recurring path is now:

`DSA analysis history -> ResearchBundle -> InvestmentProposal -> Athena`

`InvestmentProposal` is canonical JSON with a deterministic SHA-256 content
hash. It is explicitly advisory-only and contains no final quantity, delta,
cash, exposure, risk-policy decision, mandate, broker order or fill field.

`SIMULATION_EXECUTION` is retired as a runtime mode in DSA. Its historical
contracts, scorecards and reconciliation readers remain for audit and backward
compatibility, but `M2ShadowLoopService.from_config()` refuses to construct the
old DSA-sizing/M3-mandate path. The restricted scheduler uses
`PROPOSAL_HANDOFF_ONLY`; `DSA_SINGLE_BRAIN_SIMULATION_EXECUTION_AUTHORIZED`
must be false. DSA publishes once to the exact loopback Athena endpoint and
does not blindly retry an uncertain acknowledgement.

Athena owns PortfolioSnapshot, RiskPolicy, AllocationDecision, RiskDecision,
ExecutionMandate, readiness, simulation worker submission, reconciliation,
fill evidence, journal and Snapshot B. `LIVE_TRADING=false` remains mandatory.
