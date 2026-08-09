# DSA 持仓统一账户中心 v1

Status: implementation complete on `ui/portfolio-account-center-v1`; Architecture Review UI-semantic follow-up applied, pending re-review. This document is subordinate to `SINGLE_BRAIN_CONSTITUTION.md` and `DSA_UI_ARCHITECTURE_V1.md`.

## Account source model

`/portfolio` remains the sole top-level account and holdings entry. It presents two visibly separated source groups:

- **手工账户** — existing DSA-owned writable ledger. Account creation/deactivation, manual trades, cash ledger, corporate actions, CSV import, FIFO/AVG, FX refresh, risk views, and position analysis retain their existing behavior.
- **已连接账户** — one Athena-owned authoritative simulation `PortfolioSnapshot`. DSA displays this object read-only and never materializes it into the manual ledger.

The two sources are not silently aggregated. Missing connected facts are never filled from manual data, and an unavailable connected Snapshot is never presented as a zero-balance account.

## Read-only API boundary

`GET /api/v1/portfolio/connected-snapshot` is the only new backend surface.

The service reuses `CanonicalHttpPortfolioSnapshotSource`, including its exact loopback GET boundary, redirect rejection, response-receipt clock, strict contract parsing, and canonical hash validation. It additionally requires:

- `source=ATHENA_RUNTIME`;
- `authoritative=true`, `read_only=true`, `simulation_only=true`;
- `account_mode=SIMULATION` and the configured account identity;
- UTC producer timestamps;
- the accepted one-second cross-host clock-skew budget;
- a maximum Snapshot age of five minutes.

The response carries the canonical JSON object without changing Decimal strings, timestamps, IDs, revision/supersession, currency, or content hash. Reconciliation and data-quality limitations remain observable rather than being hidden.

This path does not import the manual `PortfolioService`, persistence repositories, execution contracts, broker SDKs, scheduler services, or Athena implementation modules. It has no POST/PUT/PATCH/DELETE sibling for connected-account control.

## `/portfolio` responsibilities

When a manual account is selected, the existing page remains writable under its previous rules.

When the connected account is selected, the page shows:

- connected/simulation/read-only identity;
- broker, account mode, actual Snapshot currency and producer time;
- reconciliation state, data quality, and limitations;
- equity, cash, available cash, reserved cash, and PnL;
- positions keyed exactly by `(market, symbol)`;
- canonical active-order quantities and lifecycle state;
- collapsed lineage details such as Snapshot ID, revision, producer, and content hash.

The connected view contains no manual trade, cash, corporate-action, CSV, FX mutation, account deletion, submit, cancel, retry, or reconciliation control.

## Failure semantics

Invalid, unavailable, stale, future-dated, non-UTC, wrong-account, non-authoritative, writable, or non-simulation input fails closed with a visible “已连接账户暂时不可用” state. Manual accounts remain selectable and usable.

`DEGRADED`, `PENDING_RECONCILIATION`, `UNKNOWN`, and explicit limitations are displayed as factual warning states. `UNKNOWN` is specifically rendered as pending confirmation, never success or failure/danger; low data quality may retain a danger treatment. The UI does not trigger remediation.

## Authority and navigation

Athena remains the sole authority for connected account facts. DSA remains the sole Research and Investment Decision authority. This feature is observational and creates no ResearchBundle, InvestmentDecision, ExecutionMandate, ExecutionResult, Snapshot B, retry, or portfolio mutation.

No fuzzy cross-page lineage links were added. Deterministic navigation can be added later only when an exact `(market, symbol)`, `source_report_id`, or `decision_id` target is supported.

## Deferred work and known limits

- The canonical P0 `ActiveOrder` schema does not contain limit price or market, so v1 displays only actual contract fields and does not invent either value.
- Connected and manual assets are intentionally not aggregated into one total.
- Multiple connected accounts, account connection management, trading controls, and broker lifecycle controls remain out of scope.
- The connected-account primary surface and collapsed technical-detail labels are Chinese-first; canonical identifiers and producer values remain unchanged.

## Review evidence

- Backend full gate: 5,891 passed, 4 deselected, 501 subtests passed.
- Frontend full unit suite: 1,102 passed, 2 skipped across 103 files.
- Focused backend portfolio/architecture suite: 84 passed, including all 16 connected-account cases.
- Focused frontend API/page suite: 33 passed.
- TypeScript production build and ESLint: passed.
- Playwright read-only visual suite: 3 passed.

Sanitized screenshots:

- `docs/assets/dsa-portfolio-account-center-v1-connected-desktop.png`
- `docs/assets/dsa-portfolio-account-center-v1-connected-mobile.png`
- `docs/assets/dsa-portfolio-account-center-v1-degraded.png`
- `docs/assets/dsa-portfolio-account-center-v1-manual-desktop.png`
