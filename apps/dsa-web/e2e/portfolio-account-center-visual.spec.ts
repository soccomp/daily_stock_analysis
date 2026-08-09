import { expect, test, type Page, type Route } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const evidenceDir = path.resolve(currentDir, '../../../docs/assets');

const connectedSnapshot = (degraded = false) => ({
  schema_version: '1.0',
  snapshot_id: degraded ? 'snapshot-sanitized-degraded' : 'snapshot-sanitized-reconciled',
  account_id: 'sanitized-simulation-account',
  broker: 'SANITIZED_SIMULATION',
  account_mode: 'SIMULATION',
  source: 'ATHENA_RUNTIME',
  authoritative: true,
  read_only: true,
  simulation_only: true,
  as_of: '2026-08-09T03:00:00Z',
  revision: 12,
  currency: 'HKD',
  equity: '1000000.120000',
  cash: '400000.120000',
  available_cash: '399000.120000',
  reserved_cash: '1000.000000',
  positions: [
    {
      symbol: '600519', market: 'CN', quantity: 300, available_quantity: 280,
      avg_cost: '90.120000', last_price: '100.340000', market_value: '30102.000000',
      unrealized_pnl: '3066.000000', price_as_of: '2026-08-09T03:00:00Z', price_source: 'SANITIZED_RUNTIME',
    },
    {
      symbol: '600519', market: 'HK', quantity: 20, available_quantity: 20,
      avg_cost: '88.000000', last_price: '91.000000', market_value: '1820.000000',
      unrealized_pnl: '60.000000', price_as_of: '2026-08-09T03:00:00Z', price_source: 'SANITIZED_RUNTIME',
    },
  ],
  active_orders: [{
    broker_order_id: 'sanitized-order-1', symbol: '600519', side: 'BUY', quantity: 100,
    filled_quantity: 40, remaining_quantity: 60, state: 'PARTIALLY_FILLED',
    reserved_cash: '1000.000000', submitted_at: '2026-08-09T02:59:00Z',
  }],
  realized_pnl: '120.000000',
  unrealized_pnl: '3126.000000',
  reconciliation_status: degraded ? 'DEGRADED' : 'RECONCILED',
  data_quality: degraded ? 'MEDIUM' : 'HIGH',
  limitations: degraded ? ['部分行情来自延迟报价'] : [],
  broker_snapshot_ref: 'sanitized:snapshot',
  trace_id: 'sanitized-trace',
  created_at: '2026-08-09T03:00:00Z',
  producer: 'ATHENA_RUNTIME',
  content_hash: 'a'.repeat(64),
  supersedes_id: 'snapshot-sanitized-previous',
});

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
}

async function installFacts(page: Page, degraded = false) {
  await page.addInitScript(() => localStorage.setItem('dsa.uiLanguage', 'zh'));
  await page.route('**/api/v1/auth/status', (route) => json(route, {
    authEnabled: false, loggedIn: false, passwordSet: false, passwordChangeable: false, setupState: 'no_password',
  }));
  await page.route('**/api/v1/screening/status', (route) => json(route, { enabled: false, available: false }));
  await page.route('**/api/v1/portfolio/connected-snapshot', (route) => json(route, { item: connectedSnapshot(degraded) }));
  await page.route('**/api/v1/portfolio/accounts?**', (route) => json(route, { accounts: [{
    id: 1, name: '我的手工账户', broker: 'Demo', market: 'cn', base_currency: 'CNY', is_active: true,
  }] }));
  await page.route('**/api/v1/portfolio/snapshot?**', (route) => json(route, {
    as_of: '2026-08-09', cost_method: 'fifo', currency: 'CNY', account_count: 1,
    total_cash: 100000, total_market_value: 31500, total_equity: 131500,
    realized_pnl: 0, unrealized_pnl: 1500, fee_total: 0, tax_total: 0, fx_stale: false,
    data_quality: 'ok', limitations: [], accounts: [{
      account_id: 1, account_name: '我的手工账户', broker: 'Demo', market: 'cn', base_currency: 'CNY',
      as_of: '2026-08-09', cost_method: 'fifo', total_cash: 100000, total_market_value: 31500,
      total_equity: 131500, realized_pnl: 0, unrealized_pnl: 1500, fee_total: 0, tax_total: 0,
      fx_stale: false, positions: [],
    }],
  }));
  await page.route('**/api/v1/portfolio/risk?**', (route) => json(route, {
    as_of: '2026-08-09', account_id: null, cost_method: 'fifo', currency: 'CNY', thresholds: {},
    concentration: { total_market_value: 0, top_weight_pct: 0, alert: false, top_positions: [] },
    sector_concentration: { total_market_value: 0, top_weight_pct: 0, alert: false, top_sectors: [], coverage: {}, errors: [] },
    drawdown: { series_points: 0, max_drawdown_pct: 0, current_drawdown_pct: 0, alert: false, fx_stale: false },
    stop_loss: { near_alert: false, triggered_count: 0, near_count: 0, items: [] },
    decision_signal_risk: { available: true, total: 0, actions: {}, items: [] },
  }));
  await page.route('**/api/v1/portfolio/imports/csv/brokers', (route) => json(route, { brokers: [] }));
  for (const pathname of ['trades', 'cash-ledger', 'corporate-actions']) {
    await page.route(`**/api/v1/portfolio/${pathname}?**`, (route) => json(route, {
      items: [], total: 0, page: 1, page_size: 20,
    }));
  }
}

test.describe('portfolio account center v1 visual evidence', () => {
  test('connected desktop uses authoritative facts and no mutation controls', async ({ page }) => {
    const connectedMethods: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/portfolio/connected-snapshot')) connectedMethods.push(request.method());
    });
    await installFacts(page, false);
    await page.goto('/portfolio');
    await page.getByRole('combobox').first().selectOption('connected');

    await expect(page.getByTestId('connected-account-view')).toBeVisible();
    await expect(page.getByText('已核对', { exact: true })).toBeVisible();
    await expect(page.getByText('数据质量 · 高')).toBeVisible();
    await expect(page.getByText('CN', { exact: true })).toBeVisible();
    await expect(page.getByText('HK', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '提交交易' })).toHaveCount(0);
    expect(connectedMethods.length).toBeGreaterThan(0);
    expect(connectedMethods.every((method) => method === 'GET')).toBe(true);
    await page.screenshot({ path: path.join(evidenceDir, 'dsa-portfolio-account-center-v1-connected-desktop.png'), fullPage: true });
  });

  test('connected mobile remains readable', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installFacts(page, false);
    await page.goto('/portfolio');
    await page.getByRole('combobox').first().selectOption('connected');
    await expect(page.getByTestId('connected-account-view')).toBeVisible();
    await page.screenshot({ path: path.join(evidenceDir, 'dsa-portfolio-account-center-v1-connected-mobile.png'), fullPage: true });
  });

  test('degraded facts are explicit and manual controls remain intact', async ({ page }) => {
    await installFacts(page, true);
    await page.goto('/portfolio');
    await page.getByRole('combobox').first().selectOption('connected');
    await expect(page.getByText('权威快照存在限制')).toBeVisible();
    await page.screenshot({ path: path.join(evidenceDir, 'dsa-portfolio-account-center-v1-degraded.png'), fullPage: true });

    await page.getByRole('combobox').first().selectOption('1');
    await expect(page.getByRole('button', { name: '提交交易' })).toBeVisible();
    await expect(page.getByRole('button', { name: '提交资金流水' })).toBeVisible();
    await page.screenshot({ path: path.join(evidenceDir, 'dsa-portfolio-account-center-v1-manual-desktop.png'), fullPage: true });
  });
});
