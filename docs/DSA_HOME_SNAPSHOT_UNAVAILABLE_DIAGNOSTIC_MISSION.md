# DSA Home Snapshot Unavailable — Diagnostic Mission

## Model Mode
- Model: Terra
- Reasoning: 中
- Why: narrow runtime/UI/backend diagnosis; no architecture redesign or source change is authorized.

## Goal
Explain why the DSA 首页 still shows “账户快照暂时不可用” across multiple sections even after a hard refresh, while recent direct Athena canonical Snapshot GETs were healthy and RECONCILED.

## Mode
READ-ONLY DIAGNOSTIC ONLY.

Do not modify code, config, timeout, scheduler, system clock, Athena, oMLX, launchd plist, database contents, trading permissions, or UI state. Do not trigger an extra M3 cycle or any broker mutation.

## Required checks
1. Reproduce the current 首页 response in the running M5 DSA at `127.0.0.1:8080` using read-only browser/API requests.
2. Identify the exact backend API calls/data sources each affected 首页 section uses for connected-account / authoritative snapshot data.
3. For each relevant DSA endpoint, record sanitized HTTP status, latency, and the exact returned error/status field that makes the frontend render “账户快照暂时不可用”.
4. Compare those DSA endpoints with a direct read-only Athena canonical Snapshot GET at the same time.
5. Determine whether the fault is in:
   - DSA backend snapshot ingress/client;
   - cached/persisted authority mirror used by the 首页 rather than live Athena truth;
   - frontend state/error fan-out where one failed request marks multiple sections unavailable;
   - stale API contract/field mismatch;
   - another specific cause.
6. Trace the frontend rendering path to the exact condition/message mapping for “账户快照暂时不可用”.
7. Check whether `/portfolio` connected-account view has the same failure or only 首页 does.
8. Confirm current Athena health, simulation-only/LIVE=false, Snapshot RECONCILED, scheduler topology, and pending reconciliation remain unchanged.

## Evidence standard
Prefer direct runtime evidence over inference. Capture exact endpoint names and sanitized response/error classifications, but never expose credentials, holdings detail, or secrets.

## Stop condition
Do not fix anything in this mission.

Report only:
1. root cause;
2. affected layer(s);
3. whether authoritative account truth is actually unavailable or only the DSA presentation path is broken;
4. whether the issue affects Brain/M3 execution path or UI/read-model only;
5. smallest safe fix recommendation;
6. whether the fix is an Architecture Review Gate.

Then STOP and wait for ChatGPT review.