# Single Brain M2 Baseline Status

**Status date:** 2026-08-09

**Lifecycle state:** M2 BASELINE ACCEPTED AND MERGED

**Normative parents:**

- `docs/SINGLE_BRAIN_CONSTITUTION.md`
- `docs/SINGLE_BRAIN_M2_MISSION.md`

This document is the canonical post-merge publication record for the accepted M2 Shadow Operations Readiness baseline. It supersedes only the pre-merge/Draft publication-state wording in the M2 Mission closeout section; the Mission scope, authority rules, implementation requirements, test evidence, and known gaps remain normative.

## Canonical integration branches

- DSA: `soccomp/daily_stock_analysis` branch `athena-integration`
- Athena: `soccomp/athena` branch `integration`

Future implementation missions must start from these canonical integration branches unless a later accepted baseline explicitly supersedes them.

## Accepted M2 code heads and merge baselines

### DSA

- accepted implementation head: `33edf2c6e224cd63e9a51915cbb22f564eac22ba`
- merged by PR #4
- merge commit: `38a20aaf8fe9d27873c2acb1f0152728734fe8be`
- accepted implementation tree: `1ef3c7fd3f383e95d6884941839cf8cc0ad2a6f7`
- merge baseline tree: `1ef3c7fd3f383e95d6884941839cf8cc0ad2a6f7`

### Athena

- accepted implementation head: `3649a4fca834b44e71d96630058b79652de7b833`
- merged by PR #3
- merge commit: `3840bf8bc9c381c1129f7114486b0a6f40e56ffb`
- accepted implementation tree: `9549a7ec98ef1fb5bad325785a91a3399dab2d0e`
- merge baseline tree: `9549a7ec98ef1fb5bad325785a91a3399dab2d0e`

## Tree audit

PASS.

The DSA merge commit and accepted DSA implementation head point to the same Git tree. The Athena merge commit and accepted Athena implementation head also point to the same Git tree. Therefore the merge operations changed history only; they introduced no code-tree drift relative to the tested M2 heads.

No additional full regression was required solely for these merge commits because the audited code trees are byte-identical to the already tested implementation heads.

## Accepted verification evidence

The accepted M2 implementation recorded:

- DSA required gate: 5,839 passed, 4 deselected, 501 subtests, plus syntax/critical flake8/deterministic checks.
- DSA M2 focused/auth/architecture/cross-repository suite: 52 passed.
- Athena full regression: 916 passed.
- Athena M2A + Trading Spine/worker focused suite: 92 passed.
- deterministic 20-cycle x 3-symbol shadow burn-in with 60 unique shadow scorecards and zero execution artifacts.
- cross-repository canonical snapshot proof with zero submissions/cancellations.

These are local implementation verification results; no GitHub Actions status checks were reported for the accepted heads.

## Safety state at baseline

- M2 execution authorization remains OFF.
- No M2 path authorizes mandate dispatch, broker submission, retry, cancel/replace, SELL/REDUCE, or portfolio mutation.
- `LIVE_TRADING` remains false for the M2 boundary.
- No launchd/plist/deployed runtime configuration was enabled or changed by M2 implementation or baseline promotion.
- Athena remains the sole authoritative portfolio-truth producer.
- DSA remains the sole investment decision Brain.

## Deployment smoke outcome

The governed M2 Deployment Smoke completed with terminal state `DEPLOYMENT SMOKE PASS`. Its accepted evidence remains observational and does not authorize execution. The Owner subsequently authorized continuous M2 Shadow Operations, but activation found that `--webui-only` set `DSA_RUNTIME_SCHEDULER_SUPPRESS_START=true`, so the accepted recurring M2 task was never reconciled into the running API process. Temporary activation configuration was rolled back.

## Continuous Shadow startup repair — architecture review candidate

**State:** IMPLEMENTED AND TESTED; DRAFT PR #6 OPEN; NOT MERGED; NOT DEPLOYED

The DSA-only repair preserves `--webui-only` and its ordinary scheduler suppression while adding an explicit `M2_SHADOW_ONLY` runtime scheduler mode. In that mode:

- `DSA_SINGLE_BRAIN_M2_ENABLED=false` registers no recurring task;
- `DSA_SINGLE_BRAIN_M2_ENABLED=true` registers exactly one existing `single_brain_m2_shadow` task;
- the configured M2 cadence remains unchanged (default and accepted deployment value: 60 minutes);
- no daily analysis job or Event Monitor task is registered;
- the existing shared analysis lock and M2 cycle/symbol persistence deduplication remain authoritative;
- P1A, P1B, execution authorization, mandate dispatch, and all broker operations remain outside the reachable M2 runtime path;
- the read-only M2 readiness response reports the actual scheduler mode, authority count, interval, and next registered run.

Implementation verification on the review branch recorded:

- focused startup/M2/readiness/recovery/scorecard/architecture suite: 128 passed;
- architecture boundary suite: 7 passed;
- repository backend gate: syntax PASS, critical flake8 PASS, deterministic checks PASS, 5,851 passed, 4 deselected, and 501 subtests passed.

No Athena files, canonical contracts, Snapshot semantics, decision authority, RiskPolicy semantics, persistence schemas, authentication policy, network binding, launchd/plist, or deployed configuration are changed by the repair.

## Next governed step

The repair must stop at `ARCHITECTURE REVIEW GATE: M2_WEBUI_ONLY_SCHEDULER_REPAIR_READY`. After explicit review authorization, the same Continuous Shadow Completion Mission may merge and perform a reversible DSA-only deployment and activation. Until then, M2 recurring scheduling remains OFF in the deployed service.
