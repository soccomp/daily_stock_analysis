# PALLAS-009 historical “10% overnight” root-cause evidence

Investigation date: 2026-08-22 (Asia/Shanghai)

## What was checked

- The live DSA process is `.../daily_stock_analysis/main.py --webui-only` (PID 63302 at investigation time); the running repository is `/Users/m5air/WorkBuddy/Li'ang/daily_stock_analysis`, not this implementation worktree.
- The live SQLite database `data/stock_analysis.db` exposes `analysis_history` for reports. No persisted task lifecycle, worker lease, heartbeat, or task dedupe table was found.
- The pre-corrective task queue contract was process-local: `_tasks`, `_futures`, and `_analyzing_stocks` were in-memory structures. No durable record containing the historical task ID, stage, worker ID, or heartbeat was available.
- A repository/log search found no historical record that uniquely identifies the reported “10% overnight” task. The exact task, worker, timestamps, input payload, and report hash are therefore unavailable.

## Mechanism assessment

The symptom is technically explainable as a stale UI progress projection: task startup assigned progress `10` before the blocking stock/Market Review work, while the old runtime had no durable heartbeat and did not emit truthful internal Market Review stages. A slow network tool, data source, or LLM call could therefore leave the UI showing 10% while the worker was still blocked or already lost. The old in-memory queue also allowed the task identity and liveness evidence to disappear on process restart.

This mechanism can explain a progress/liveness illusion. It cannot establish that the historical task actually had that cause because the original task evidence is gone. It also cannot change a computed overnight return, market price, report content, or order state: the queue progress field was observational metadata, not a calculation or execution authority.

## Corrective boundary

This record intentionally does not substitute a new run for the missing historical evidence. The corrective candidate now persists task identity/lifecycle metadata, runs worker heartbeats through long-running execution, reconciles abandoned tasks on startup/runtime, and exposes stage/heartbeat/worker identity in the UI. Those changes prevent recurrence and make a future incident auditable; they do not retroactively recover the unavailable task.
