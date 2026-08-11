# DSA Local LLM Latency Alignment v1 — Deployment Mission

## Model Mode

- Model: **Sol**
- Reasoning: **High / 高**
- Why: this is a deployment alignment and runtime-safety verification task on M5; it must preserve exact reviewed source, simulation-only authority, scheduler uniqueness, and local oMLX routing without broad engineering work.

---

# Deployment Target

Repository: `soccomp/daily_stock_analysis`

Canonical integration branch after PR #13 merge: `athena-integration`

**Exact application commit to deploy:**

`7fbb748a9731b79f91363a15be604b62a7613894`

This is the merge commit for PR #13 and contains reviewed implementation head:

`2bfc2c03345944e69cc48cf47a84c40dc3222857`

The deployment-mission documentation commit itself is governance only. **Do not deploy the docs commit as the app target in place of `7fbb748a...`; the running DSA source must be the exact PR #13 merge application commit above.**

---

# Goal

Deploy DSA on the M5 to exact application SHA `7fbb748a9731b79f91363a15be604b62a7613894`, preserving the current local oMLX/Qwen3 runtime configuration and all existing Single Brain safety boundaries.

Then perform the smallest safe smoke needed to prove source/runtime alignment and readiness for the next natural scheduler cycle.

Do **not** force a production analysis cycle or broker-simulation mutation solely for acceptance.

---

# Frozen Runtime / Safety Boundaries

Must remain unchanged:

- DSA launchd service: `com.dsa.webui`
- DSA loopback UI/API binding: `127.0.0.1:8080`
- effective text generation route: local oMLX only
- local model: `Qwen3-14B-MLX-6bit`
- oMLX loopback/auth posture
- `LIVE_TRADING=false`
- Athena simulation-only account
- M3 mode: `M3_SIMULATION_EXECUTION_ONLY`
- exactly one active M3 scheduler
- cadence: `3600` seconds
- P1A/P1B schedulers OFF
- BUY/ADD/HOLD only; no SELL/REDUCE expansion
- RiskPolicy
- 300-second PortfolioSnapshot freshness rule
- exact-quantity / UNKNOWN-reconcile / no-blind-retry semantics
- broker permissions
- network/auth exposure
- manual portfolio ledger semantics

No Athena source change. No oMLX tuning. No scheduler acceleration.

---

# Deployment Procedure

1. Record pre-deploy running DSA SHA, process/launchd state, scheduler state, pending reconciliation count, Athena readiness, simulation/LIVE facts, and effective local LLM route in sanitized form.
2. Fetch `origin/athena-integration` and verify merge commit `7fbb748a9731b79f91363a15be604b62a7613894` exists and has reviewed PR #13 head `2bfc2c...` as a parent.
3. Align the M5 DSA application checkout/runtime to exact SHA `7fbb748a9731b79f91363a15be604b62a7613894` using the existing deployment method. Do not carry source edits from another branch/worktree into the runtime tree.
4. Preserve M5-only runtime secrets/configuration, especially the local oMLX API credential. Never print or post secrets.
5. Restart/reload only what is required for DSA source alignment. Do not change Athena or oMLX unless an ordinary DSA restart requires reconnect observation.
6. Verify the running DSA process resolves to exact app SHA `7fbb748a...`.

---

# Minimum Post-Deploy Smoke

Collect sanitized evidence only.

Required:

- `com.dsa.webui` loaded/running
- DSA responds on `127.0.0.1:8080`
- exact running DSA source SHA = `7fbb748a9731b79f91363a15be604b62a7613894`
- local oMLX route remains effective and model remains `Qwen3-14B-MLX-6bit`
- Athena status = READY or existing healthy equivalent
- Athena remains `LIVE_TRADING=false`
- connected account remains simulation-only
- authoritative PortfolioSnapshot can be read safely
- pending reconciliation count = 0 before declaring ready
- exactly one `M3_SIMULATION_EXECUTION_ONLY` scheduler
- scheduler cadence = 3600 seconds
- P1A/P1B OFF
- no unexpected broker order/execution mutation caused by deployment/smoke
- no manual-ledger mutation

Use GET/read-only checks wherever possible.

---

# Natural-Cycle Validation

Do not manually trigger the M3 scheduler solely for this deployment.

If a natural scheduler cycle starts while this mission is running, observe it without accelerating/retrying it and report:

1. cycle start/end/status;
2. whether local oMLX/Qwen3 Research succeeds;
3. Analyzer duration and whether bounded completion is used;
4. whether the final pre-Brain Athena Snapshot refresh occurs and is fresh;
5. whether an InvestmentDecision is produced;
6. whether any mandate is produced;
7. broker submission/result if naturally applicable;
8. exact fail-closed reason if it stops.

If no natural cycle completes during the deployment window, that is **not a deployment failure**. Report `NATURAL_CYCLE_PENDING` and stop after smoke.

---

# Acceptance

PASS only if:

- running DSA exact SHA is `7fbb748a9731b79f91363a15be604b62a7613894`;
- launchd/web UI is healthy on loopback;
- local Qwen route is preserved;
- Athena is healthy, simulation-only, LIVE false;
- scheduler topology remains exactly one M3 at 3600s, P1A/P1B off;
- pending reconciliation is zero;
- no safety boundary or trading capability changed;
- deployment itself caused no broker/manual-ledger mutation.

Natural-cycle proof may remain pending.

---

# AUTONOMOUS BLOCKER — RESOLVE AND CONTINUE

Routine deployment blockers are autonomous: stale local checkout, clean restart, launchd reload, port/PID verification, dependency/runtime path alignment, read-only smoke failures caused by ordinary local state, and sanitized evidence collection.

Resolve, verify, and continue without asking the Owner to relay logs.

---

# OWNER HARD STOP

Stop only if deployment would require:

- LIVE or real-money trading
- SELL/REDUCE expansion
- RiskPolicy changes
- scheduler cadence changes
- auth/network exposure changes
- broker permission changes
- destructive/irreversible migration
- forced broker-simulation mutation
- Athena source/deployment changes affecting execution behavior
- secret rotation/exposure requiring Owner action

---

# Closeout

Post a concise sanitized deployment closeout to PR #13 (or the canonical deployment evidence location already used by the repo) containing:

- exact target app SHA
- exact running SHA
- launchd/UI health
- local model route/model identity
- Athena READY/LIVE/simulation facts
- scheduler topology/cadence
- pending reconciliation
- broker/manual-ledger mutation check
- natural-cycle result, or `NATURAL_CYCLE_PENDING`
- limitations

Then STOP. No new model benchmark, soak, tuning, SELL/REDUCE, or unrelated work.