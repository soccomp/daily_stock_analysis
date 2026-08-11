import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test';

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

const snapshot = {
  schema_version: '1.0', snapshot_id: 'snapshot-sanitized-overview', account_id: 'sanitized-account',
  broker: 'SANITIZED_SIMULATION', account_mode: 'SIMULATION', source: 'ATHENA_RUNTIME', authoritative: true,
  read_only: true, simulation_only: true, as_of: '2026-08-11T01:05:00Z', revision: 18, currency: 'HKD',
  equity: '1000000.120000', cash: '400000.120000', available_cash: '399000.120000', reserved_cash: '1000.000000',
  positions: [
    { symbol: '600519', market: 'CN', quantity: 300, available_quantity: 280, avg_cost: '90.120000', last_price: '100.340000', market_value: '30102.000000', unrealized_pnl: '3066.000000', price_as_of: '2026-08-11T01:05:00Z', price_source: 'SANITIZED_RUNTIME' },
    { symbol: '600519', market: 'HK', quantity: 20, available_quantity: 20, avg_cost: '88.000000', last_price: '91.000000', market_value: '1820.000000', unrealized_pnl: '60.000000', price_as_of: '2026-08-11T01:05:00Z', price_source: 'SANITIZED_RUNTIME' },
  ],
  active_orders: [], realized_pnl: '120.000000', unrealized_pnl: '3126.000000',
  reconciliation_status: 'RECONCILED', data_quality: 'HIGH', limitations: [], broker_snapshot_ref: 'sanitized:snapshot',
  trace_id: 'sanitized-trace', created_at: '2026-08-11T01:05:00Z', producer: 'ATHENA_RUNTIME', content_hash: 'a'.repeat(64), supersedes_id: 'snapshot-sanitized-previous',
};

function decision(decisionId: string, action: 'HOLD' | 'ADD' | 'BUY', executionStatus: string, mode = 'SIMULATION_EXECUTION') {
  const delta = action === 'HOLD' ? 0 : action === 'ADD' ? 200 : 100;
  return {
    decision_id: decisionId, created_at: '2026-08-11T01:08:00Z', source_report_id: 1,
    account_id: 'sanitized-account', symbol: '600519', market: 'CN', action,
    current_quantity: action === 'BUY' ? 0 : 300, target_quantity: action === 'HOLD' ? 300 : action === 'ADD' ? 500 : 100,
    delta_quantity: delta, confidence: '0.82', rationale: action === 'HOLD' ? '现有仓位已达到风险预算目标。' : '风险预算允许本轮目标变化。',
    mode, execution_status: executionStatus,
    reconciliation_status: executionStatus === 'UNKNOWN' ? 'PENDING_RECONCILIATION' : 'NOT_REQUIRED',
    requested_quantity: action === 'HOLD' ? null : delta, submitted_quantity: 0, filled_quantity: 0,
    remaining_quantity: action === 'HOLD' ? null : delta, block_reason: executionStatus === 'BLOCKED' ? 'MARKET_SESSION_CLOSED' : null,
    broker_reason: null, snapshot_b_available: false,
  };
}

async function installOverviewFacts(page: Page, options: { unavailable?: boolean } = {}) {
  await page.addInitScript(() => localStorage.setItem('dsa.uiLanguage', 'zh'));
  await page.route('**/api/v1/auth/status', (route) => json(route, { auth_enabled: false, logged_in: false, password_set: false, password_changeable: false, setup_state: 'no_password' }));
  await page.route('**/api/v1/screening/status', (route) => json(route, { enabled: false, available: false }));
  await page.route('**/api/v1/system/config/setup/status', (route) => json(route, { is_complete: true, ready_for_smoke: true, required_missing_keys: [], next_step_key: null, checks: [] }));
  await page.route('**/api/v1/agent/skills', (route) => json(route, { skills: [], default_skill_id: '' }));
  await page.route('**/api/v1/stocks/watchlist', (route) => json(route, { stock_codes: ['600519', '000001'] }));
  await page.route('**/api/v1/analysis/tasks?**', (route) => json(route, { total: 0, pending: 0, processing: 0, tasks: [] }));
  await page.route('**/api/v1/history/stocks?**', (route) => json(route, { total: 1, items: [{ id: 1, stock_code: '600519', stock_name: '贵州茅台', report_type: 'detailed', sentiment_score: 78, operation_advice: '中期趋势保持积极', analysis_count: 1, last_analysis_time: '2026-08-11T01:03:00Z' }] }));
  await page.route('**/api/v1/history/1', (route) => json(route, { meta: { id: 1, query_id: 'q-sanitized', stock_code: '600519', stock_name: '贵州茅台', report_type: 'detailed', report_language: 'zh', created_at: '2026-08-11T01:03:00Z' }, summary: { analysis_summary: '趋势保持积极', operation_advice: '中期趋势保持积极', trend_prediction: '震荡偏强', sentiment_score: 78 } }));
  await page.route('**/api/v1/history?**', (route) => json(route, { total: 1, page: 1, limit: 100, items: [{ id: 1, query_id: 'q-sanitized', stock_code: '600519', stock_name: '贵州茅台', report_type: 'detailed', sentiment_score: 78, operation_advice: '中期趋势保持积极', created_at: '2026-08-11T01:03:00Z' }] }));
  await page.route('**/api/v1/portfolio/connected-snapshot', (route) => options.unavailable ? json(route, { detail: 'snapshot unavailable' }, 503) : json(route, { item: snapshot }));
  await page.route('**/api/v1/decision-scorecards?**', (route) => {
    const mode = new URL(route.request().url()).searchParams.get('mode');
    if (mode !== 'SIMULATION_EXECUTION') return json(route, { detail: 'mode required' }, 400);
    return json(route, { items: [decision('decision-hold', 'HOLD', 'NOT_APPLICABLE'), decision('decision-blocked', 'ADD', 'BLOCKED'), decision('decision-unknown', 'BUY', 'UNKNOWN'), decision('decision-shadow', 'BUY', 'NOT_AUTHORIZED', 'M2_SHADOW')], total: 4, page: 1, page_size: 20 });
  });
  await page.route('**/api/v1/single-brain/m2/readiness', (route) => json(route, { item: {
    feature_enabled: true, execution_mode: 'SIMULATION_EXECUTION', execution_authorization: 'ON',
    recurring_scheduler: { enabled: true, mode: 'M3_SIMULATION_EXECUTION_ONLY', authority_count: 1, interval_seconds: 3600, next_run_at: '2026-08-11T02:00:00Z' },
    latest_authoritative_snapshot: { as_of: '2026-08-11T01:05:00Z', reconciliation_status: 'RECONCILED' },
    latest_cycle: { scheduled_for: '2026-08-11T01:00:00Z', completed_at: '2026-08-11T01:10:00Z', status: 'COMPLETED' },
    simulation_execution: { pending_execution_count: 0, latest_execution_state: 'NOT_APPLICABLE' },
  } }));
  await page.route('**/api/v1/alerts/unread-count', (route) => json(route, { count: 0 }));
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
}

test.describe('daily overview v1 visual evidence', () => {
  test('desktop shows connected facts, decisions, research, and status semantics', async ({ page }, testInfo) => {
    await installOverviewFacts(page);
    await page.goto('/');
    await expect(page.getByTestId('daily-overview')).toBeVisible();
    await expect(page.getByText('HKD 1,000,000.12')).toBeVisible();
    await expect(page.getByText('HKD 1,000,000.12')).toHaveCSS('color', 'rgb(248, 250, 252)');
    await expect(page.getByTestId('overview-holding-CN-600519')).toBeVisible();
    await expect(page.getByTestId('overview-holding-HK-600519')).toBeVisible();
    await expect(page.getByText('继续持有，本轮无需交易', { exact: true })).toBeVisible();
    await expect(page.getByText('市场已休市', { exact: true })).toBeVisible();
    await expect(page.getByTestId('overview-execution-decision-unknown')).toHaveText('状态待确认');
    await expect(page.getByTestId('overview-execution-decision-shadow')).toHaveCount(0);
    await expect(page.getByText('模拟执行授权：开启')).toBeVisible();
    await expect(page.getByTestId('overview-timeline-decision-decision-hold')).toHaveAttribute('data-tone', 'neutral');
    await capture(page, testInfo, 'daily-overview-desktop');
    await page.getByRole('heading', { name: '当前持仓' }).scrollIntoViewIfNeeded();
    await capture(page, testInfo, 'daily-overview-holdings');
    await page.getByRole('heading', { name: '今日投资决策' }).evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await capture(page, testInfo, 'daily-overview-decisions');
  });

  test('mobile keeps the operating-priority order readable', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installOverviewFacts(page);
    await page.goto('/');
    await expect(page.getByTestId('daily-overview')).toBeVisible();
    await expect(page.getByText('自动投资状态')).toBeVisible();
    await expect(page.getByText('账户概览')).toBeVisible();
    await expect(page.getByText('需要关注')).toBeVisible();
    await capture(page, testInfo, 'daily-overview-mobile');
  });

  test('connected unavailable remains explicit while research and decisions survive', async ({ page }, testInfo) => {
    await installOverviewFacts(page, { unavailable: true });
    await page.goto('/');
    await expect(page.getByText('已连接账户暂时不可用')).toBeVisible();
    await expect(page.getByText('贵州茅台', { exact: true })).toBeVisible();
    await expect(page.getByTestId('overview-execution-decision-hold')).toBeVisible();
    await expect(page.getByText(/HKD 0\.00|CNY 0\.00/)).toHaveCount(0);
    await capture(page, testInfo, 'daily-overview-connected-unavailable');
  });

  test('research workbench and connected portfolio deep-link remain intact', async ({ page }, testInfo) => {
    await installOverviewFacts(page);
    await page.goto('/');
    await page.getByRole('tab', { name: '研究工作台' }).click();
    await expect(page.getByPlaceholder(/输入股票/)).toBeVisible();
    await capture(page, testInfo, 'daily-overview-research-workbench');

    await page.goto('/portfolio?account=connected');
    await expect(page.getByTestId('connected-account-view')).toBeVisible();
    await capture(page, testInfo, 'daily-overview-connected-portfolio');
  });
});
