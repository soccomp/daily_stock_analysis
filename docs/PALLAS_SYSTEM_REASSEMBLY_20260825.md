# PALLAS system reassembly — candidate contract

This candidate reassembles the DSA side of Athena Issue #42 without adding a
new process manager, scheduler thread, daemon, readiness store, or journal.

## Active topology

- `RuntimeSchedulerService` remains the single recurring authority.
- `single_brain_proposal_handoff` remains the one recurring task; the existing
  `DailyScreeningScheduler` is invoked as a bounded due-check substep before
  proposal handoff, not as a second runtime scheduler.
- The standalone `com.dsa.screening-scheduler` is not part of the target
  production authority map; controlled LaunchAgent retirement is deployment-
  reserved.
- `DailyMarketContextService` produces persisted context when the canonical
  cycle has no admissible context; `MarketReviewLinkageRepository` resolves
  and admits the same context for the cycle cutoff.
- Existing `ProposalHandoffLoopService` remains the only DSA path from
  screening/holdings to ResearchTrigger, ResearchBundle, InvestmentProposal,
  and Athena ACK.

## Admission and failure contract

MarketContext admission is point-in-time and structural: identity/linkage,
trade date, decision cutoff, freshness, completeness, component PIT evidence,
and persistence are explicit.  `FUTURE_DATED`, `STALE`,
`DEGRADED_STRUCTURAL`, `INVALID_PIT`, `PERSISTENCE_FAILED`, and identity
conflicts fail closed.  Luna narrative failure leaves persisted structured
market data usable and is represented as structured-fallback metadata.

The lightweight rules-first simulation path does not proactively generate a
market review and does not block a cycle when that optional context is absent;
it records `MARKET_CONTEXT_OPTIONAL_RULES_MODE` and continues with deterministic
DSA rules.  A context that is explicitly supplied is still validated by the
contract, and callers that require strict MarketContext admission retain the
fail-closed behavior above.

Screening discovery consumes the existing durable `screening_runs` producer
and distinguishes `VALID`, `NO_FRESH_CANDIDATES`, `DISCOVERY_MISSING`,
`DISCOVERY_STALE`, `DISCOVERY_FAILED`, `DISCOVERY_QUALITY_FAILED`, and
`DISCOVERY_UNAVAILABLE`.  A proven zero result records durable `NO_ACTION`;
an unavailable screening source may continue an explicitly proven holdings
path but remains `PARTIAL` and never becomes a false screening success.

## Deterministic evidence

The DSA half is exercised by:

```text
PYTHONPATH=. python scripts/pallas_system_reassembly_dsa_harness.py --scenario success
```

It uses a fixed clock, isolated SQLite state, a loopback snapshot, deterministic
fixtures, and a Luna Max metadata contract (`gpt-5.6-luna`, `max`, no real
call/fallback).  Its fault matrix covers calendar-unavailable admission,
structural/PIT/freshness/persistence/identity rejection, narrative failure with
usable structured context, missing/stale/failed/quality-failed screening,
research timeout fail-closed, and uncertain proposal transport with exactly one
POST plus one read-only lookup.  It never invokes a provider, Worker, order,
deployment, or production service.
