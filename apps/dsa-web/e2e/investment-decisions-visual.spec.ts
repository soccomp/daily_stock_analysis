import { expect, test, type Page, type Route } from '@playwright/test';

const summaries = [
  {
    decision_id: 'decision-ui-blocked',
    created_at: '2026-08-09T03:02:00Z',
    source_report_id: 42,
    account_id: 'sanitized-simulation-account',
    symbol: '600519',
    market: 'CN',
    action: 'ADD',
    current_quantity: 300,
    target_quantity: 1200,
    delta_quantity: 900,
    confidence: '0.84',
    rationale: '中期研究证据偏多，风险预算与账户约束允许增加持仓。',
    mode: 'SIMULATION_EXECUTION',
    execution_status: 'BLOCKED',
    reconciliation_status: 'RECONCILED',
    requested_quantity: 900,
    submitted_quantity: 0,
    filled_quantity: 0,
    remaining_quantity: 900,
    average_fill_price: null,
    block_reason: 'MARKET_SESSION_CLOSED',
    broker_reason: null,
    snapshot_b_available: true,
  },
  {
    decision_id: 'decision-ui-hold',
    created_at: '2026-08-09T02:02:00Z',
    source_report_id: 41,
    account_id: 'sanitized-simulation-account',
    symbol: '000001',
    market: 'CN',
    action: 'HOLD',
    current_quantity: 500,
    target_quantity: 500,
    delta_quantity: 0,
    confidence: '0.71',
    rationale: '当前持仓已达到本轮风险预算目标，继续观察经营与价格条件。',
    mode: 'SIMULATION_EXECUTION',
    execution_status: 'NOT_APPLICABLE',
    reconciliation_status: 'NOT_APPLICABLE',
    requested_quantity: null,
    submitted_quantity: null,
    filled_quantity: null,
    remaining_quantity: null,
    average_fill_price: null,
    block_reason: null,
    broker_reason: null,
    snapshot_b_available: false,
  },
  {
    decision_id: 'decision-ui-unknown',
    created_at: '2026-08-09T01:02:00Z',
    source_report_id: 40,
    account_id: 'sanitized-simulation-account',
    symbol: '600000',
    market: 'CN',
    action: 'BUY',
    current_quantity: 0,
    target_quantity: 200,
    delta_quantity: 200,
    confidence: '0.76',
    rationale: '基本面与技术面证据一致，风险预算允许建立初始持仓。',
    mode: 'SIMULATION_EXECUTION',
    execution_status: 'UNKNOWN',
    reconciliation_status: 'PENDING_RECONCILIATION',
    requested_quantity: 200,
    submitted_quantity: 200,
    filled_quantity: 0,
    remaining_quantity: 200,
    average_fill_price: null,
    block_reason: null,
    broker_reason: null,
    snapshot_b_available: true,
  },
];

const snapshot = (id: string, asOf: string) => ({
  schema_version: '1.0',
  snapshot_id: id,
  content_hash: 'b'.repeat(64),
  account_id: 'sanitized-simulation-account',
  broker: 'SANITIZED_SIMULATION',
  account_mode: 'SIMULATION',
  source: 'ATHENA_RUNTIME',
  authoritative: true,
  read_only: true,
  simulation_only: true,
  as_of: asOf,
  revision: 12,
  currency: 'CNY',
  equity: '1000000.00',
  cash: '400000.00',
  available_cash: '400000.00',
  reserved_cash: '0.00',
  positions: [{
    symbol: '600519',
    market: 'CN',
    quantity: 300,
    available_quantity: 300,
    avg_cost: '100.00',
    last_price: '105.00',
    market_value: '31500.00',
    unrealized_pnl: '1500.00',
    price_as_of: asOf,
    price_source: 'SANITIZED_RUNTIME',
  }],
  active_orders: [],
  realized_pnl: '0.00',
  unrealized_pnl: '1500.00',
  reconciliation_status: 'RECONCILED',
  data_quality: 'HIGH',
  limitations: [],
  broker_snapshot_ref: 'sanitized:snapshot',
  trace_id: 'sanitized-trace',
  created_at: asOf,
  producer: 'ATHENA_RUNTIME',
  supersedes_id: null,
});

function scorecard(decisionId: string) {
  const summary = summaries.find((item) => item.decision_id === decisionId) ?? summaries[0];
  const actionable = summary.action !== 'HOLD';
  const result = actionable ? {
    result_id: `result-${decisionId}`,
    status: summary.execution_status,
    requested_quantity: summary.requested_quantity,
    submitted_quantity: summary.submitted_quantity,
    filled_quantity: summary.filled_quantity,
    remaining_quantity: summary.remaining_quantity,
    requested_limit_price: '105.00',
    average_fill_price: null,
    fees: '0.00',
    slippage_bps: null,
    block_reason: summary.block_reason,
    broker_reason: null,
    reconciliation_status: summary.reconciliation_status,
    retry_forbidden: true,
  } : null;
  return {
    scorecard_hash: 'a'.repeat(64),
    created_at: summary.created_at,
    source_report_id: summary.source_report_id,
    research_bundle: {
      research_id: `research-${decisionId}`,
      market_regime: '震荡偏强',
      industry_view: '行业景气稳定',
      fundamental_view: '盈利质量稳健',
      technical_view: '中期趋势保持完整',
      valuation_view: '估值处于合理区间',
      intel_view: '暂无异常情报',
      capital_flow_view: '资金流向中性偏多',
      bull_case: '需求改善带动盈利上修',
      base_case: '经营按当前趋势发展',
      bear_case: '需求转弱造成估值回落',
      catalysts: ['业绩改善', '渠道库存恢复'],
      risk_factors: ['需求波动', '估值收缩'],
      invalidation_conditions: ['跌破研究失效条件'],
      confidence: summary.confidence,
      data_quality: 'HIGH',
    },
    portfolio_snapshot_a: snapshot('snapshot-a', '2026-08-09T03:00:00Z'),
    risk_policy: {
      policy_id: 'policy-sanitized',
      policy_version: '1.0',
      max_single_position_weight: '0.15',
      max_total_exposure: '0.80',
      min_cash_weight: '0.10',
      risk_budget_per_trade: '0.01',
      max_concurrent_positions: 10,
      stop_required: true,
      allowed_markets: ['CN'],
      effective_from: '2026-08-09T00:00:00Z',
      effective_until: null,
    },
    investment_decision: {
      decision_id: summary.decision_id,
      content_hash: 'c'.repeat(64),
      decision_cycle_id: 'cycle-sanitized',
      symbol: summary.symbol,
      market: summary.market,
      action: summary.action,
      current_quantity: summary.current_quantity,
      current_weight: '0.03',
      target_quantity: summary.target_quantity,
      target_weight: '0.12',
      delta_quantity: summary.delta_quantity,
      entry_plan: { limit_price: '105.00', order_type: 'LIMIT' },
      stop_plan: actionable ? { stop_price: '95.00' } : null,
      take_profit_plan: actionable ? { target_price: '125.00' } : null,
      expected_return: '0.12',
      expected_risk: '0.08',
      confidence: summary.confidence,
      rationale: summary.rationale,
      risk_reasoning: '数量由风险预算与账户约束共同限制。',
      valid_from: '2026-08-09T03:00:00Z',
      valid_until: '2026-08-09T05:00:00Z',
    },
    decision_signal: {},
    execution_mandate: actionable ? {
      mandate_id: `mandate-${decisionId}`,
      quantity: summary.delta_quantity,
      limit_price: '105.00',
      order_type: 'LIMIT',
      side: 'BUY',
      time_in_force: 'DAY',
    } : null,
    execution_results: result ? [result] : [],
    portfolio_snapshot_b: summary.snapshot_b_available
      ? snapshot('snapshot-b', '2026-08-09T03:02:00Z')
      : null,
    execution_diagnostics: {
      mode: 'SIMULATION_EXECUTION',
      execution_authorization: 'ON',
      execution_state: summary.execution_status,
    },
  };
}

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installReadOnlyFacts(page: Page) {
  await page.addInitScript(() => localStorage.setItem('dsa.uiLanguage', 'zh'));
  await page.route('**/api/v1/auth/status', (route) => json(route, {
    authEnabled: false,
    loggedIn: false,
    passwordSet: false,
    passwordChangeable: false,
    setupState: 'no_password',
  }));
  await page.route('**/api/v1/screening/status', (route) => json(route, {
    enabled: false,
    available: false,
  }));
  await page.route('**/api/v1/single-brain/m2/readiness', (route) => json(route, {
    item: {
      feature_enabled: true,
      execution_mode: 'SIMULATION_EXECUTION',
      execution_authorization: 'ON',
      recurring_scheduler: {
        enabled: true,
        mode: 'M3_SIMULATION_EXECUTION_ONLY',
        authority_count: 1,
        interval_seconds: 3600,
        next_run_at: '2026-08-09T04:00:00Z',
      },
      latest_authoritative_snapshot: {
        as_of: '2026-08-09T03:00:00Z',
        reconciliation_status: 'RECONCILED',
      },
      latest_cycle: {
        scheduled_for: '2026-08-09T03:00:00Z',
        completed_at: '2026-08-09T03:02:00Z',
        status: 'COMPLETED',
      },
      simulation_execution: {
        pending_execution_count: 1,
        latest_execution_state: 'UNKNOWN',
      },
    },
  }));
  await page.route('**/api/v1/decision-scorecards?**', (route) => json(route, {
    items: summaries,
    total: summaries.length,
    page: 1,
    page_size: 10,
  }));
  await page.route(/\/api\/v1\/decision-scorecards\/([^?]+)$/, (route) => {
    const decisionId = decodeURIComponent(route.request().url().split('/').at(-1) ?? '');
    return json(route, { item: scorecard(decisionId) });
  });
}

test.describe('investment decisions v1 visual evidence', () => {
  test('desktop list and drawer preserve read-only execution semantics', async ({ page }, testInfo) => {
    const methods: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/single-brain/m2/') || request.url().includes('/decision-scorecards')) {
        methods.push(request.method());
      }
    });
    await installReadOnlyFacts(page);
    await page.goto('/investment-decisions');

    await expect(page.getByRole('heading', { name: '投资决策' })).toBeVisible();
    await expect(page.getByText('继续持有，本轮无需交易。')).toBeVisible();
    await expect(page.getByText('交易状态仍待核对，系统不会盲目重试。')).toBeVisible();
    await expect(page.getByText(/执行说明：市场已休市/)).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('investment-decisions-desktop.png'), fullPage: true });

    await page.getByRole('button', { name: '查看 600519 决策档案' }).click();
    await expect(page.getByRole('heading', { name: '600519 决策档案' })).toBeVisible();
    await expect(page.getByText('决策前账户')).toBeVisible();
    await expect(page.getByText('决策后账户')).toBeVisible();
    await page.waitForTimeout(350);
    await page.screenshot({ path: testInfo.outputPath('investment-decisions-drawer-desktop.png') });

    expect(methods.length).toBeGreaterThan(0);
    expect(methods.every((method) => method === 'GET')).toBe(true);
  });

  test('mobile deep link restores the readable decision archive', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installReadOnlyFacts(page);
    await page.goto('/investment-decisions?decision=decision-ui-unknown');

    await expect(page.getByRole('heading', { name: '600000 决策档案' })).toBeVisible();
    await expect(page.getByText('状态仍待确认')).toBeVisible();
    await expect(page.getByText('系统正在等待账户事实核对，不会自动再次提交。')).toBeVisible();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box?.width ?? 0).toBeLessThanOrEqual(390);
    await page.waitForTimeout(350);
    await page.screenshot({ path: testInfo.outputPath('investment-decisions-mobile-drawer.png') });

    await page.reload();
    await expect(page.getByRole('heading', { name: '600000 决策档案' })).toBeVisible();
  });
});
