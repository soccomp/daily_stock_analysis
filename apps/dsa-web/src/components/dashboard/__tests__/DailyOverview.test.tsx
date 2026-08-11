import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DecisionScorecardSummary, SingleBrainReadiness } from '../../../types/investmentDecisions';
import type { ConnectedPortfolioSnapshot } from '../../../types/portfolio';
import DailyOverview from '../DailyOverview';

const { getConnectedSnapshot, listDecisions, getReadiness } = vi.hoisted(() => ({
  getConnectedSnapshot: vi.fn(),
  listDecisions: vi.fn(),
  getReadiness: vi.fn(),
}));

vi.mock('../../../api/portfolio', () => ({ portfolioApi: { getConnectedSnapshot } }));
vi.mock('../../../api/investmentDecisions', () => ({
  investmentDecisionsApi: { list: listDecisions, readiness: getReadiness },
}));

const snapshot: ConnectedPortfolioSnapshot = {
  schemaVersion: '1.0',
  snapshotId: 'snapshot-overview-1',
  accountId: 'sanitized-account',
  broker: 'SANITIZED_SIMULATION',
  accountMode: 'SIMULATION',
  source: 'ATHENA_RUNTIME',
  authoritative: true,
  readOnly: true,
  simulationOnly: true,
  asOf: '2026-08-11T01:05:00Z',
  revision: 9,
  currency: 'HKD',
  equity: '1000000.120000',
  cash: '400000.120000',
  availableCash: '399000.120000',
  reservedCash: '1000.000000',
  positions: [
    {
      market: 'CN', symbol: '600519', quantity: 300, availableQuantity: 280,
      avgCost: '90.120000', lastPrice: '100.340000', marketValue: '30102.000000',
      unrealizedPnl: '3066.000000', priceAsOf: '2026-08-11T01:05:00Z', priceSource: 'SANITIZED_RUNTIME',
    },
    {
      market: 'HK', symbol: '600519', quantity: 20, availableQuantity: 20,
      avgCost: '88.000000', lastPrice: '91.000000', marketValue: '1820.000000',
      unrealizedPnl: '60.000000', priceAsOf: '2026-08-11T01:05:00Z', priceSource: 'SANITIZED_RUNTIME',
    },
  ],
  activeOrders: [],
  realizedPnl: '120.000000',
  unrealizedPnl: '3126.000000',
  reconciliationStatus: 'RECONCILED',
  dataQuality: 'HIGH',
  limitations: [],
  brokerSnapshotRef: 'sanitized:snapshot',
  traceId: 'sanitized-trace',
  createdAt: '2026-08-11T01:05:00Z',
  producer: 'ATHENA_RUNTIME',
  contentHash: 'a'.repeat(64),
  supersedesId: 'snapshot-overview-0',
};

function decision(overrides: Partial<DecisionScorecardSummary>): DecisionScorecardSummary {
  return {
    decisionId: 'decision-hold',
    createdAt: '2026-08-11T01:08:00Z',
    sourceReportId: 1,
    accountId: 'sanitized-account',
    symbol: '600519',
    market: 'CN',
    action: 'HOLD',
    currentQuantity: 300,
    targetQuantity: 300,
    deltaQuantity: 0,
    confidence: '0.82',
    rationale: '现有仓位已达到风险预算目标。',
    mode: 'SIMULATION_EXECUTION',
    executionStatus: 'NOT_APPLICABLE',
    reconciliationStatus: 'NOT_APPLICABLE',
    requestedQuantity: null,
    submittedQuantity: null,
    filledQuantity: null,
    remainingQuantity: null,
    averageFillPrice: null,
    blockReason: null,
    brokerReason: null,
    snapshotBAvailable: false,
    ...overrides,
  };
}

const readiness: SingleBrainReadiness = {
  featureEnabled: true,
  executionMode: 'SIMULATION_EXECUTION',
  executionAuthorization: 'ON',
  recurringScheduler: {
    enabled: true,
    mode: 'M3_SIMULATION_EXECUTION_ONLY',
    authorityCount: 1,
    intervalSeconds: 3600,
    nextRunAt: '2026-08-11T02:00:00Z',
  },
  latestAuthoritativeSnapshot: { asOf: snapshot.asOf, reconciliationStatus: 'RECONCILED' },
  latestCycle: { scheduledFor: '2026-08-11T01:00:00Z', completedAt: '2026-08-11T01:10:00Z', status: 'COMPLETED' },
  simulationExecution: { pendingExecutionCount: 0, latestExecutionState: 'NOT_APPLICABLE' },
};

const researchItems = [{
  id: 1,
  stockCode: '600519',
  stockName: '贵州茅台',
  analysisCount: 1,
  lastAnalysisTime: '2026-08-11T01:03:00Z',
  operationAdvice: '中期趋势保持积极',
  sentimentScore: 78,
}];

function renderOverview(overrides: Partial<React.ComponentProps<typeof DailyOverview>> = {}) {
  const props: React.ComponentProps<typeof DailyOverview> = {
    researchItems,
    researchLoading: false,
    researchUnavailable: false,
    activeTasks: [],
    watchlistCovered: 1,
    watchlistTotal: 2,
    latestMarketReviewAt: '2026-08-11T00:30:00Z',
    onOpenResearch: vi.fn(),
    onOpenWorkbench: vi.fn(),
    onNavigate: vi.fn(),
    ...overrides,
  };
  return { ...render(<DailyOverview {...props} />), props };
}

describe('DailyOverview', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-11T02:00:00Z'));
    getConnectedSnapshot.mockResolvedValue(snapshot);
    listDecisions.mockResolvedValue({
      items: [
        decision({}),
        decision({
          decisionId: 'decision-blocked', action: 'ADD', targetQuantity: 500, deltaQuantity: 200,
          executionStatus: 'BLOCKED', reconciliationStatus: 'NOT_REQUIRED', requestedQuantity: 200,
          submittedQuantity: 0, filledQuantity: 0, remainingQuantity: 200, blockReason: 'MARKET_SESSION_CLOSED',
        }),
        decision({
          decisionId: 'decision-unknown', action: 'BUY', currentQuantity: 0, targetQuantity: 100,
          deltaQuantity: 100, executionStatus: 'UNKNOWN', reconciliationStatus: 'PENDING_RECONCILIATION',
          requestedQuantity: 100, submittedQuantity: 100, filledQuantity: 0, remainingQuantity: 100,
        }),
        decision({
          decisionId: 'decision-shadow', action: 'BUY', currentQuantity: 0, targetQuantity: 50,
          deltaQuantity: 50, mode: 'M2_SHADOW', executionStatus: 'NOT_AUTHORIZED',
        }),
      ],
      total: 4,
      page: 1,
      pageSize: 20,
    });
    getReadiness.mockResolvedValue(readiness);
  });

  afterEach(() => vi.useRealTimers());

  it('shows authoritative account, exact instrument identities, research, decisions, and runtime facts', async () => {
    const { props } = renderOverview();

    expect(await screen.findByText('HKD 1,000,000.12')).toBeInTheDocument();
    expect(screen.queryByText(/CNY 1,000,000/)).not.toBeInTheDocument();
    expect(screen.getByTestId('overview-holding-CN-600519')).toBeInTheDocument();
    expect(screen.getByTestId('overview-holding-HK-600519')).toBeInTheDocument();
    expect(screen.getByText('共 2 项持仓')).toBeInTheDocument();
    expect(listDecisions).toHaveBeenCalledWith({ page: 1, pageSize: 20, mode: 'SIMULATION_EXECUTION' });
    expect(screen.queryByTestId('overview-execution-decision-shadow')).not.toBeInTheDocument();
    expect(screen.getByText('模拟执行授权：开启')).toHaveClass('text-success');
    expect(screen.getByText('研究观点', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '今日投资决策' })).toBeInTheDocument();
    expect(screen.getAllByText('继续持有，本轮无需交易', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('市场已休市', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('执行指令：未生成（本轮无需交易）')).toBeInTheDocument();
    expect(screen.getByText('执行指令：已生成 · 200 股')).toBeInTheDocument();
    expect(screen.getAllByText('券商提交：未提交')).toHaveLength(2);
    expect(screen.getByText('券商提交：状态待确认 · 记录数量 100 股')).toBeInTheDocument();

    const unknownBadge = screen.getByTestId('overview-execution-decision-unknown');
    expect(unknownBadge).toHaveTextContent('状态待确认');
    expect(unknownBadge).toHaveClass('text-warning');
    expect(unknownBadge).not.toHaveClass('text-danger');
    expect(screen.getByTestId('overview-timeline-decision-decision-hold')).toHaveAttribute('data-tone', 'neutral');
    expect(screen.getByTestId('overview-timeline-decision-decision-blocked')).toHaveAttribute('data-tone', 'warning');
    expect(screen.getByTestId('overview-timeline-decision-decision-unknown')).toHaveAttribute('data-tone', 'warning');

    fireEvent.click(screen.getByRole('button', { name: '查看全部持仓' }));
    expect(props.onNavigate).toHaveBeenCalledWith('/portfolio?account=connected');
    fireEvent.click(screen.getByText('贵州茅台').closest('button')!);
    expect(props.onOpenResearch).toHaveBeenCalledWith(researchItems[0]);
  });

  it('isolates source failures and never fabricates zero or manual portfolio facts', async () => {
    getConnectedSnapshot.mockRejectedValueOnce(new Error('worker unavailable'));
    renderOverview();

    expect(await screen.findByText('已连接账户暂时不可用')).toBeInTheDocument();
    expect(screen.getByText('无法显示当前持仓')).toBeInTheDocument();
    expect(screen.queryByText(/HKD 0\.00|CNY 0\.00/)).not.toBeInTheDocument();
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(await screen.findByTestId('overview-execution-decision-hold')).toBeInTheDocument();
  });

  it('shows empty research independently from available account and decisions', async () => {
    renderOverview({ researchItems: [], researchUnavailable: false });
    expect(await screen.findByText('HKD 1,000,000.12')).toBeInTheDocument();
    expect(screen.getByText('今天还没有完成研究')).toBeInTheDocument();
    expect(screen.getByTestId('overview-execution-decision-hold')).toBeInTheDocument();
  });

  it('treats contradictory simulation execution authorization as a warning fact', async () => {
    getReadiness.mockResolvedValueOnce({ ...readiness, executionAuthorization: 'OFF' });
    renderOverview();

    expect(await screen.findByText('执行授权：状态待确认')).toHaveClass('text-warning');
    expect(screen.getByText('模拟执行授权或运行模式需要核对')).toBeInTheDocument();
  });

  it('maps decision timeline tones by decision and execution semantics', async () => {
    listDecisions.mockResolvedValueOnce({
      items: [
        decision({ decisionId: 'timeline-hold' }),
        decision({ decisionId: 'timeline-filled', action: 'BUY', currentQuantity: 0, targetQuantity: 100, deltaQuantity: 100, executionStatus: 'FILLED' }),
        decision({ decisionId: 'timeline-active', action: 'ADD', targetQuantity: 400, deltaQuantity: 100, executionStatus: 'ACTIVE' }),
        decision({ decisionId: 'timeline-rejected', action: 'BUY', currentQuantity: 0, targetQuantity: 100, deltaQuantity: 100, executionStatus: 'BROKER_REJECTED' }),
      ],
      total: 4,
      page: 1,
      pageSize: 20,
    });
    renderOverview();

    expect(await screen.findByTestId('overview-timeline-decision-timeline-hold')).toHaveAttribute('data-tone', 'neutral');
    expect(screen.getByTestId('overview-timeline-decision-timeline-filled')).toHaveAttribute('data-tone', 'success');
    expect(screen.getByTestId('overview-timeline-decision-timeline-active')).toHaveAttribute('data-tone', 'info');
    expect(screen.getByTestId('overview-timeline-decision-timeline-rejected')).toHaveAttribute('data-tone', 'danger');
  });

  it('uses the required mobile information order classes without page-wide horizontal overflow', async () => {
    const { container } = renderOverview();
    await waitFor(() => expect(getReadiness).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="daily-overview"]')).toHaveClass('space-y-4');
    expect(container.querySelector('.overflow-x-auto')).not.toBeInTheDocument();
    expect(screen.getByText('自动投资状态').closest('.terminal-card')).toHaveClass('order-1');
    expect(screen.getByText('账户概览').closest('.terminal-card')).toHaveClass('order-2');
  });
});
