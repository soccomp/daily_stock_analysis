import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { investmentDecisionsApi } from '../../api/investmentDecisions';
import type {
  DecisionScorecardDetail,
  DecisionScorecardSummary,
  SingleBrainReadiness,
} from '../../types/investmentDecisions';
import InvestmentDecisionsPage from '../InvestmentDecisionsPage';

vi.mock('../../api/investmentDecisions', () => ({
  investmentDecisionsApi: {
    list: vi.fn(),
    get: vi.fn(),
    readiness: vi.fn(),
  },
}));

const readiness: SingleBrainReadiness = {
  featureEnabled: true,
  executionMode: 'SIMULATION_EXECUTION',
  executionAuthorization: 'ON',
  recurringScheduler: {
    enabled: true,
    mode: 'M3_SIMULATION_EXECUTION_ONLY',
    authorityCount: 1,
    intervalSeconds: 3600,
    nextRunAt: '2026-08-09T04:00:00Z',
  },
  latestAuthoritativeSnapshot: {
    asOf: '2026-08-09T03:00:00Z',
    reconciliationStatus: 'RECONCILED',
  },
  latestCycle: {
    scheduledFor: '2026-08-09T03:00:00Z',
    completedAt: '2026-08-09T03:02:00Z',
    status: 'COMPLETED',
  },
  simulationExecution: {
    pendingExecutionCount: 1,
    latestExecutionState: 'UNKNOWN',
  },
};

const blocked: DecisionScorecardSummary = {
  decisionId: 'decision-blocked',
  createdAt: '2026-08-09T03:02:00Z',
  sourceReportId: 42,
  accountId: 'sanitized-account',
  symbol: '600519',
  market: 'CN',
  action: 'ADD',
  currentQuantity: 300,
  targetQuantity: 1200,
  deltaQuantity: 900,
  confidence: '0.84',
  rationale: '研究证据偏多，风险预算与账户约束允许增加持仓。',
  mode: 'SIMULATION_EXECUTION',
  executionStatus: 'BLOCKED',
  reconciliationStatus: 'RECONCILED',
  requestedQuantity: 900,
  submittedQuantity: 0,
  filledQuantity: 0,
  remainingQuantity: 900,
  averageFillPrice: null,
  blockReason: 'MARKET_SESSION_CLOSED',
  brokerReason: null,
  snapshotBAvailable: true,
};

const hold: DecisionScorecardSummary = {
  ...blocked,
  decisionId: 'decision-hold',
  symbol: '000001',
  action: 'HOLD',
  currentQuantity: 500,
  targetQuantity: 500,
  deltaQuantity: 0,
  rationale: '现有持仓已达到本轮风险预算目标。',
  executionStatus: 'NOT_APPLICABLE',
  reconciliationStatus: 'NOT_APPLICABLE',
  requestedQuantity: null,
  submittedQuantity: null,
  filledQuantity: null,
  remainingQuantity: null,
  blockReason: null,
  snapshotBAvailable: false,
};

const unknown: DecisionScorecardSummary = {
  ...blocked,
  decisionId: 'decision-unknown',
  symbol: '600000',
  action: 'BUY',
  currentQuantity: 0,
  targetQuantity: 200,
  deltaQuantity: 200,
  executionStatus: 'UNKNOWN',
  reconciliationStatus: 'PENDING_RECONCILIATION',
  requestedQuantity: 200,
  submittedQuantity: 200,
  filledQuantity: 0,
  remainingQuantity: 200,
  blockReason: null,
  snapshotBAvailable: true,
};

function detailFor(summary: DecisionScorecardSummary): DecisionScorecardDetail {
  return {
    scorecardHash: 'a'.repeat(64),
    createdAt: summary.createdAt,
    sourceReportId: summary.sourceReportId,
    researchBundle: {
      researchId: `research-${summary.decisionId}`,
      marketRegime: '震荡偏强',
      industryView: '行业景气稳定',
      fundamentalView: '盈利质量稳健',
      technicalView: '趋势保持完整',
      valuationView: '估值处于合理区间',
      intelView: '暂无异常情报',
      capitalFlowView: '资金流向中性偏多',
      bullCase: '需求改善带动盈利上修',
      baseCase: '经营按当前趋势发展',
      bearCase: '需求转弱造成估值回落',
      catalysts: ['业绩改善'],
      riskFactors: ['需求波动'],
      invalidationConditions: ['跌破研究失效条件'],
      confidence: '0.84',
      dataQuality: 'HIGH',
    },
    portfolioSnapshotA: {
      snapshotId: 'snapshot-a',
      contentHash: 'b'.repeat(64),
      accountMode: 'SIMULATION',
      currency: 'HKD',
      source: 'ATHENA_RUNTIME',
      authoritative: true,
      readOnly: true,
      simulationOnly: true,
      asOf: '2026-08-09T03:00:00Z',
      equity: '1000000.00',
      cash: '400000.00',
      availableCash: '400000.00',
      reservedCash: '0.00',
      reconciliationStatus: 'RECONCILED',
      positions: [
        {
          symbol: summary.symbol,
          market: 'HK',
          quantity: 999,
          availableQuantity: 999,
          avgCost: '9.00',
          lastPrice: '9.50',
          marketValue: '9490.50',
        },
        {
          symbol: summary.symbol,
          market: summary.market,
          quantity: summary.currentQuantity,
          availableQuantity: summary.currentQuantity,
          avgCost: '100.00',
          lastPrice: '105.00',
          marketValue: '31500.00',
        },
      ],
    },
    riskPolicy: {
      policyId: 'policy-ui',
      policyVersion: '1.0',
      maxSinglePositionWeight: '0.15',
      maxTotalExposure: '0.80',
      minCashWeight: '0.10',
      riskBudgetPerTrade: '0.01',
      maxConcurrentPositions: 10,
      stopRequired: true,
      allowedMarkets: ['CN'],
      effectiveFrom: '2026-08-09T00:00:00Z',
      effectiveUntil: null,
    },
    investmentDecision: {
      decisionId: summary.decisionId,
      contentHash: 'c'.repeat(64),
      decisionCycleId: 'cycle-ui',
      symbol: summary.symbol,
      market: summary.market,
      action: summary.action,
      currentQuantity: summary.currentQuantity,
      currentWeight: '0.03',
      targetQuantity: summary.targetQuantity,
      targetWeight: '0.12',
      deltaQuantity: summary.deltaQuantity,
      entryPlan: { limitPrice: '105.00', orderType: 'LIMIT' },
      stopPlan: { stopPrice: '95.00' },
      takeProfitPlan: { targetPrice: '125.00' },
      expectedReturn: '0.12',
      expectedRisk: '0.08',
      confidence: '0.84',
      rationale: summary.rationale,
      riskReasoning: '数量由风险预算与账户约束共同限制。',
      validFrom: '2026-08-09T03:00:00Z',
      validUntil: '2026-08-09T05:00:00Z',
    },
    decisionSignal: {},
    executionMandate: summary.action === 'HOLD' ? null : {
      mandateId: `mandate-${summary.decisionId}`,
      quantity: summary.deltaQuantity,
      limitPrice: '105.00',
      orderType: 'LIMIT',
      side: 'BUY',
      timeInForce: 'DAY',
    },
    executionResults: summary.action === 'HOLD' ? [] : [{
      resultId: `result-${summary.decisionId}`,
      status: summary.executionStatus!,
      requestedQuantity: summary.requestedQuantity!,
      submittedQuantity: summary.submittedQuantity!,
      filledQuantity: summary.filledQuantity!,
      remainingQuantity: summary.remainingQuantity!,
      requestedLimitPrice: '105.00',
      averageFillPrice: null,
      fees: '0.00',
      slippageBps: null,
      blockReason: summary.blockReason,
      brokerReason: summary.brokerReason,
      reconciliationStatus: summary.reconciliationStatus!,
      retryForbidden: true,
    }],
    portfolioSnapshotB: summary.snapshotBAvailable ? {
      ...detailSnapshot(),
      snapshotId: 'snapshot-b',
      contentHash: 'd'.repeat(64),
      asOf: '2026-08-09T03:02:00Z',
    } : null,
    executionDiagnostics: {
      mode: 'SIMULATION_EXECUTION',
      executionAuthorization: 'ON',
      executionState: summary.executionStatus,
    },
  };
}

function detailSnapshot() {
  return {
    snapshotId: 'snapshot-a',
    contentHash: 'b'.repeat(64),
    accountMode: 'SIMULATION',
    currency: 'HKD',
    source: 'ATHENA_RUNTIME',
    authoritative: true,
    readOnly: true,
    simulationOnly: true,
    asOf: '2026-08-09T03:00:00Z',
    equity: '1000000.00',
    cash: '400000.00',
    availableCash: '400000.00',
    reservedCash: '0.00',
    reconciliationStatus: 'RECONCILED' as const,
    positions: [],
  };
}

function renderPage(entry = '/investment-decisions') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <InvestmentDecisionsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(investmentDecisionsApi.readiness).mockResolvedValue(readiness);
  vi.mocked(investmentDecisionsApi.list).mockResolvedValue({
    items: [blocked, hold, unknown],
    total: 3,
    page: 1,
    pageSize: 10,
  });
  vi.mocked(investmentDecisionsApi.get).mockImplementation(async (decisionId) => {
    const item = [blocked, hold, unknown].find((candidate) => candidate.decisionId === decisionId);
    if (!item) throw new Error('not found');
    return detailFor(item);
  });
});

describe('InvestmentDecisionsPage', () => {
  it('renders Chinese-first runtime facts and keeps HOLD separate from BLOCKED', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: '投资决策' })).toBeInTheDocument();
    expect(screen.getByText('查看自动投资的决策、执行情况和账户变化。')).toBeInTheDocument();
    expect(screen.getByText('运行中')).toBeInTheDocument();
    expect(screen.getAllByText('模拟交易').length).toBeGreaterThan(0);
    expect(screen.getByText('继续持有，本轮无需交易。')).toBeInTheDocument();
    expect(screen.getByText(/市场已休市/)).toBeInTheDocument();
    expect(screen.getAllByText('已阻止').length).toBeGreaterThan(0);
    expect(screen.getAllByText('决策置信度 84.00%').length).toBeGreaterThan(0);
    expect(screen.queryByText('投资决策失败')).not.toBeInTheDocument();

    const blockedCard = screen.getByRole('button', { name: '查看 600519 决策档案' }).closest('.rounded-2xl');
    expect(blockedCard).not.toBeNull();
    expect(within(blockedCard as HTMLElement).getByText('请求数量')).toBeInTheDocument();
    expect(within(blockedCard as HTMLElement).getByText('提交数量')).toBeInTheDocument();
    expect(within(blockedCard as HTMLElement).getByText('成交数量')).toBeInTheDocument();
    expect(investmentDecisionsApi.list).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'SIMULATION_EXECUTION',
    }));
  });

  it('shows UNKNOWN as pending confirmation and never as failure', async () => {
    renderPage();

    expect((await screen.findAllByText('状态待确认')).length).toBeGreaterThan(0);
    expect(screen.getByText('交易状态仍待核对，系统不会盲目重试。')).toBeInTheDocument();
    expect(screen.queryByText('交易失败')).not.toBeInTheDocument();
  });

  it('restores a decision archive from the deep link and closes without mutation controls', async () => {
    renderPage('/investment-decisions?decision=decision-unknown');

    expect(await screen.findByRole('heading', { name: '600000 决策档案' })).toBeInTheDocument();
    expect(investmentDecisionsApi.get).toHaveBeenCalledWith('decision-unknown');
    expect(screen.getByText('研究依据')).toBeInTheDocument();
    expect(screen.getByText('决策前账户')).toBeInTheDocument();
    expect(screen.getByText('风险约束')).toBeInTheDocument();
    expect(screen.getByText('决策后账户')).toBeInTheDocument();
    expect(screen.getAllByText('决策置信度').length).toBeGreaterThan(0);
    expect(screen.getAllByText('1,000,000.00 HKD').length).toBeGreaterThan(0);
    expect(screen.getAllByText('105.00 HKD').length).toBeGreaterThan(0);
    expect(screen.queryByText('999 股')).not.toBeInTheDocument();
    expect(screen.queryByText(/ CNY$/)).not.toBeInTheDocument();
    expect(screen.getByText('系统正在等待账户事实核对，不会自动再次提交。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /重试|提交|买入|卖出|撤单/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '关闭抽屉' }));
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '600000 决策档案' })).not.toBeInTheDocument();
    });
  });

  it('does not synthesize a Snapshot B for HOLD', async () => {
    renderPage('/investment-decisions?decision=decision-hold');

    expect(await screen.findByText('本轮无需交易。')).toBeInTheDocument();
    expect(screen.getByText('尚无决策后账户快照')).toBeInTheDocument();
  });
});
