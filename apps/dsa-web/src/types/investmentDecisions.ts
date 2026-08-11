export type InvestmentAction = 'BUY' | 'ADD' | 'HOLD';
export type ExecutionStatus =
  | 'ACCEPTED'
  | 'ACTIVE'
  | 'PARTIALLY_FILLED'
  | 'FILLED'
  | 'BLOCKED'
  | 'BROKER_REJECTED'
  | 'EXPIRED'
  | 'CANCELLED'
  | 'UNKNOWN'
  | 'NOT_AUTHORIZED'
  | 'NOT_APPLICABLE';

export type ReconciliationStatus =
  | 'NOT_REQUIRED'
  | 'PENDING_RECONCILIATION'
  | 'RECONCILED'
  | 'DEGRADED'
  | 'UNKNOWN'
  | 'NOT_APPLICABLE';

export interface DecisionScorecardSummary {
  decisionId: string;
  createdAt: string;
  sourceReportId: number;
  accountId: string;
  symbol: string;
  market: string;
  action: InvestmentAction;
  currentQuantity: number;
  targetQuantity: number;
  deltaQuantity: number;
  confidence: string;
  rationale: string;
  mode?: string | null;
  executionStatus?: ExecutionStatus | null;
  reconciliationStatus?: ReconciliationStatus | null;
  requestedQuantity?: number | null;
  submittedQuantity?: number | null;
  filledQuantity?: number | null;
  remainingQuantity?: number | null;
  averageFillPrice?: string | null;
  blockReason?: string | null;
  brokerReason?: string | null;
  snapshotBAvailable: boolean;
}

export interface DecisionScorecardListParams {
  page?: number;
  pageSize?: number;
  symbol?: string;
  action?: InvestmentAction;
  mode?: string;
  sourceReportId?: number;
}

export interface DecisionScorecardListResponse {
  items: DecisionScorecardSummary[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ResearchBundleView {
  researchId: string;
  marketRegime: string;
  industryView: string;
  fundamentalView: string;
  technicalView: string;
  valuationView: string;
  intelView: string;
  capitalFlowView: string;
  bullCase: string;
  baseCase: string;
  bearCase: string;
  catalysts: string[];
  riskFactors: string[];
  invalidationConditions: string[];
  confidence: string;
  dataQuality: string;
}

export interface PortfolioPositionView {
  symbol: string;
  market: string;
  quantity: number;
  availableQuantity: number;
  avgCost: string;
  lastPrice: string;
  marketValue: string;
}

export interface PortfolioSnapshotView {
  snapshotId: string;
  contentHash: string;
  accountMode: string;
  currency: string;
  source: string;
  authoritative: boolean;
  readOnly: boolean;
  simulationOnly: boolean;
  asOf: string;
  equity: string;
  cash: string;
  availableCash: string;
  reservedCash: string;
  reconciliationStatus: ReconciliationStatus;
  positions: PortfolioPositionView[];
}

export interface RiskPolicyView {
  policyId: string;
  policyVersion: string;
  maxSinglePositionWeight: string;
  maxTotalExposure: string;
  minCashWeight: string;
  riskBudgetPerTrade: string;
  maxConcurrentPositions: number;
  stopRequired: boolean;
  allowedMarkets: string[];
  effectiveFrom: string;
  effectiveUntil?: string | null;
}

export interface InvestmentDecisionView {
  decisionId: string;
  contentHash: string;
  decisionCycleId: string;
  symbol: string;
  market: string;
  action: InvestmentAction;
  currentQuantity: number;
  currentWeight: string;
  targetQuantity: number;
  targetWeight: string;
  deltaQuantity: number;
  entryPlan: { limitPrice: string; orderType: string };
  stopPlan?: { stopPrice: string } | null;
  takeProfitPlan?: { targetPrice: string } | null;
  expectedReturn: string;
  expectedRisk: string;
  confidence: string;
  rationale: string;
  riskReasoning: string;
  validFrom: string;
  validUntil: string;
}

export interface ExecutionMandateView {
  mandateId: string;
  quantity: number;
  limitPrice: string;
  orderType: string;
  side: string;
  timeInForce: string;
}

export interface ExecutionResultView {
  resultId: string;
  status: ExecutionStatus;
  requestedQuantity: number;
  submittedQuantity: number;
  filledQuantity: number;
  remainingQuantity: number;
  requestedLimitPrice: string;
  averageFillPrice?: string | null;
  fees: string;
  slippageBps?: string | null;
  blockReason?: string | null;
  brokerReason?: string | null;
  reconciliationStatus: ReconciliationStatus;
  retryForbidden: boolean;
}

export interface DecisionScorecardDetail {
  scorecardHash: string;
  createdAt: string;
  sourceReportId: number;
  researchBundle: ResearchBundleView;
  portfolioSnapshotA: PortfolioSnapshotView;
  riskPolicy: RiskPolicyView;
  investmentDecision: InvestmentDecisionView;
  decisionSignal: Record<string, unknown>;
  executionMandate?: ExecutionMandateView | null;
  executionResults: ExecutionResultView[];
  portfolioSnapshotB?: PortfolioSnapshotView | null;
  executionDiagnostics: Record<string, unknown>;
}

export interface SingleBrainReadiness {
  featureEnabled: boolean;
  executionMode: string;
  executionAuthorization: 'ON' | 'OFF';
  recurringScheduler: {
    enabled: boolean;
    mode: string;
    authorityCount: number;
    intervalSeconds?: number | null;
    nextRunAt?: string | null;
  };
  latestAuthoritativeSnapshot?: {
    asOf: string;
    reconciliationStatus: ReconciliationStatus;
  } | null;
  latestCycle?: {
    scheduledFor?: string | null;
    completedAt?: string | null;
    status: string;
  } | null;
  latestCycleDiagnostics?: {
    decisionCycleId: string;
    status: string;
    failureStage?: 'RESEARCH' | 'AUTHORITY_INPUT' | 'DECISION' | 'EXECUTION' | 'CYCLE' | null;
    failureCode?: string | null;
    failureSummary?: string | null;
    expectedSymbolCount: number;
    researchCompletedCount: number;
    researchCompleted: boolean;
    decisionCount: number;
    decisionCreated: boolean;
    mandateCount?: number | null;
    mandateCreated?: boolean | null;
    dispatchAttemptCount?: number | null;
    brokerSubmissionState: 'NONE' | 'RECORDED' | 'UNKNOWN';
    recordedSubmittedQuantity?: number | null;
  } | null;
  simulationExecution?: {
    pendingExecutionCount?: number;
    latestExecutionState?: string | null;
  };
}
