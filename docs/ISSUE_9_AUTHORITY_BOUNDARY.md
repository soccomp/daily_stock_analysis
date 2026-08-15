# Issue #9 Authority Boundary

Issue #9 supersedes the former M3 authority statement for all current runtime
decisions. DSA is authoritative for market/universe analysis, screening,
research, thesis, action, confidence, expected return, price plan and an
optional advisory target-weight suggestion.

The normal recurring path is now:

`DSA analysis history -> ResearchBundle -> InvestmentProposal -> Athena`

Research objects are selected through the existing M2 selector, not a second
proposal-only universe. Every cycle reads Athena's authoritative canonical
portfolio snapshot, takes positive CN holdings first up to
`DSA_SINGLE_BRAIN_M2_HOLDINGS_LIMIT`, appends the existing
`DSA_SINGLE_BRAIN_M2_SYMBOLS` allowlist, de-duplicates, and applies
`DSA_SINGLE_BRAIN_M2_MAX_SYMBOLS`. Each selected symbol retains a
`HOLDING`/`ALLOWLIST`/`BOTH` reason in the cycle result and runtime log so the
system can answer why that name was researched.

`InvestmentProposal` is canonical JSON with a deterministic SHA-256 content
hash. It is explicitly advisory-only and contains no final quantity, delta,
cash, exposure, risk-policy decision, mandate, broker order or fill field.

`SIMULATION_EXECUTION` is retired as a runtime mode in DSA. Its historical
contracts, scorecards and reconciliation readers remain for audit and backward
compatibility, but `M2ShadowLoopService.from_config()` refuses to construct the
old DSA-sizing/M3-mandate path. The restricted scheduler uses
`PROPOSAL_HANDOFF_ONLY`; `DSA_SINGLE_BRAIN_SIMULATION_EXECUTION_AUTHORIZED`
must be false. DSA publishes once to the exact loopback Athena endpoint and
does not blindly retry an uncertain acknowledgement. Athena first returns a
durable handoff ACK containing `proposal_id`, `proposal_hash`,
`acknowledgement_id` and `acknowledgement_state=ACCEPTED`; DSA records that as a
successful handoff independently of Athena's later execution result. The legal
Athena lifecycle states are `ACCEPTED`, `NO_ACTION`, `ALLOCATED`, `BLOCKED`,
`BLOCKED_PRE_SUBMISSION`, `PENDING_RECONCILIATION`, `REJECTED` and `FILLED`.
None is reinterpreted as an invalid DSA proposal state. If the POST response is
uncertain, DSA performs one read-only ACK lookup by proposal ID and never
repeats the POST.

Athena owns PortfolioSnapshot, RiskPolicy, AllocationDecision, RiskDecision,
ExecutionMandate, readiness, simulation worker submission, reconciliation,
fill evidence, journal and Snapshot B. `LIVE_TRADING=false` remains mandatory.
