# Issue #42 corrective analysis

## Root cause

`scripts/pallas_system_reassembly_dsa_harness.py` isolated its database and screening state in a temporary directory but left `DSA_DEPENDENCY_HEALTH_PATH` unset. The production default dependency-health store could therefore receive deterministic fixture MarketContext observations.

## Corrective scope

- Route the existing dependency-health repository to the harness temporary directory before the natural scheduler scenarios start.
- Keep the production scheduler, MarketContext service, canonical cycle repository, and business authority model unchanged.
- Emit the isolated store path in harness evidence so qualification can prove that fixture state did not enter the production truth path.

## Non-goals

- No new health gate, store type, scheduler, watcher, daemon, or runtime authority.
- No production provider, Luna, Worker, broker, deployment, restart, or order call.
