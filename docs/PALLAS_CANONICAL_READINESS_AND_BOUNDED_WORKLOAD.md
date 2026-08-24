# Pallas canonical readiness and bounded natural workload

Issue #41 separates readiness by authority instead of treating every dependency as one flat gate.

- DSA owns `LLM_RESEARCH`, `RESEARCH_MARKET_DATA`, `MARKET_CONTEXT`, and advisory `NEWS_SEARCH` facts.
- Athena owns proposal intake, pre-trade data, calendar, investment authority, and simulation worker facts.
- DSA never reports Athena or worker health as local truth. Athena consumes only DSA-owned facts and builds the aggregate readiness view.

`DSA_RESEARCH_READINESS` is an observed-health projection, not a global
autonomous-trading label. Natural admission uses a separate can-attempt
decision: expired or transiently failed Luna/research-market observations may
be refreshed by the next legal natural operation, while model/provider/identity
configuration mismatches, missing providers, and missing causal market context
remain fail-closed.

Qualifying Luna generation keeps its existing 900-second default TTL. Naturally completed research-market provider calls use `DSA_RESEARCH_MARKET_DATA_HEALTH_TTL_SECONDS` (default 3600); persisted market context uses the recurring interval as its maximum age. Snapshot reads age expired evidence to `STALE` without making a provider call.

The natural `single_brain_proposal_handoff` task is admitted only during an authoritative XSHG regular session. Non-trading days, pre/post-market, and lunch terminate as durable `SKIPPED` cycles; an unknown/unavailable calendar terminates as durable `BLOCKED` with `TRADING_CALENDAR_UNAVAILABLE`. All terminate before lock acquisition and create no research, proposal, replay, or execution work.

Every admitted cycle persists a deadline. The deadline is bounded by both the actual start and the scheduler-owned due interval, less `DSA_SINGLE_BRAIN_M2_CYCLE_GUARD_SECONDS`. Before each expensive candidate, remaining time must cover the configured generation, snapshot, and proposal timeout contract. Otherwise the candidate is persisted as `DEFERRED_BUDGET`; its durable trigger remains eligible for fair selection in a later legal cycle.

`reasoning=max`, serial candidate processing, Athena-only execution authority, simulation-only operation, and the Mission-1 canonical lifecycle remain unchanged.
