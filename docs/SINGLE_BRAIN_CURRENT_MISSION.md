# Single Brain — Current Mission

**Current Mission:** M3 — Autonomous Simulation Trading v1  
**Canonical mission spec:** `docs/SINGLE_BRAIN_M3_AUTONOMOUS_SIMULATION_TRADING_V1_MISSION.md`  
**Status:** READY TO START  
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

The one planned human gate for M3 is:

`M3 SIMULATION EXECUTION REVIEW GATE`

Stop there before the first broker-mutating simulation order in the running deployment. Before that gate, complete the maximum safe implementation/test/review preparation autonomously.
