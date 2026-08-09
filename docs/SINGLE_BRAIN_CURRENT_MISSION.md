# Single Brain — Current Mission

**Current Mission:** M3 — Autonomous Simulation Trading v1  
**Canonical mission spec:** `docs/SINGLE_BRAIN_M3_AUTONOMOUS_SIMULATION_TRADING_V1_MISSION.md`  
**Status:** M3 AUTONOMOUS SIMULATION TRADING V1 PASS
**Recommended Codex mode:** Sol  
**Recommended reasoning:** 极高

## Codex start instruction

Read the canonical mission spec above from the current `athena-integration` branch and execute it as one end-to-end Mission.

Do not ask the Owner to copy/paste the Mission text. GitHub is the canonical shared fact layer.

Follow Autonomous Mission Execution Policy v1.0:

- ordinary blockers: resolve autonomously and continue;
- architecture changes: stop only at a concrete Architecture Review Gate after maximum safe work is complete;
- Owner escalation: only for genuine Owner-level product/risk/security/real-money decisions;
- do not split implementation, testing, deployment preparation, canary, reconciliation, and closeout into separate Owner-managed missions.

The one planned human gate for M3 was approved and closed:

`M3 SIMULATION EXECUTION REVIEW GATE`

M3 is now the active long-running simulation-only operating baseline. Future
missions must continue to preserve Single Brain authority, exact-quantity or
zero-submit execution, durable UNKNOWN/restart semantics, and
`LIVE_TRADING=false` unless a new Owner mission explicitly changes scope.
