import type {
  ExecutionStatus,
  InvestmentAction,
  ReconciliationStatus,
} from '../../types/investmentDecisions';

export type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history';

export const actionPresentation: Record<InvestmentAction, { label: string; variant: BadgeVariant }> = {
  BUY: { label: '买入', variant: 'info' },
  ADD: { label: '加仓', variant: 'info' },
  HOLD: { label: '持有', variant: 'default' },
};

export const executionPresentation: Record<ExecutionStatus, { label: string; variant: BadgeVariant }> = {
  ACCEPTED: { label: '已接受', variant: 'info' },
  ACTIVE: { label: '挂单中', variant: 'info' },
  PARTIALLY_FILLED: { label: '部分成交', variant: 'info' },
  FILLED: { label: '已成交', variant: 'success' },
  BLOCKED: { label: '已阻止', variant: 'warning' },
  BROKER_REJECTED: { label: '券商拒绝', variant: 'danger' },
  EXPIRED: { label: '已过期', variant: 'warning' },
  CANCELLED: { label: '已取消', variant: 'default' },
  UNKNOWN: { label: '状态待确认', variant: 'warning' },
  NOT_AUTHORIZED: { label: '未授权执行', variant: 'default' },
  NOT_APPLICABLE: { label: '无需交易', variant: 'default' },
};

export const reconciliationPresentation: Record<ReconciliationStatus, { label: string; variant: BadgeVariant }> = {
  NOT_REQUIRED: { label: '无需核对', variant: 'default' },
  PENDING_RECONCILIATION: { label: '待核对', variant: 'warning' },
  RECONCILED: { label: '已核对', variant: 'success' },
  DEGRADED: { label: '核对受限', variant: 'warning' },
  UNKNOWN: { label: '状态待确认', variant: 'warning' },
  NOT_APPLICABLE: { label: '无需核对', variant: 'default' },
};

const blockReasonLabels: Record<string, string> = {
  MARKET_SESSION_CLOSED: '市场已休市',
  PORTFOLIO_SNAPSHOT_STALE: '账户快照已变化',
  INVALID_LOT_SIZE: '数量不符合最小交易单位',
  LIVE_TRADING_NOT_FALSE: '交易环境安全状态不符合要求',
  DUPLICATE_MANDATE: '执行指令已处理',
  DUPLICATE_INTENT: '相同交易意图已处理',
  ACTIVE_CONFLICTING_ORDER: '存在冲突中的挂单',
  BROKER_UNAVAILABLE: '模拟交易服务暂不可用',
  PORTFOLIO_FILL_MISMATCH: '账户成交事实需要进一步核对',
};

export function blockReasonLabel(reason?: string | null): string | null {
  if (!reason) return null;
  return blockReasonLabels[reason] ?? '执行条件未满足';
}

export function executionLabel(status?: ExecutionStatus | null): { label: string; variant: BadgeVariant } {
  if (!status) return { label: '尚无执行结果', variant: 'default' };
  return executionPresentation[status] ?? { label: '状态待确认', variant: 'warning' };
}

export function reconciliationLabel(status?: ReconciliationStatus | null): { label: string; variant: BadgeVariant } | null {
  if (!status) return null;
  return reconciliationPresentation[status] ?? { label: '状态待确认', variant: 'warning' };
}

export function dataQualityLabel(quality: string): string {
  return ({ HIGH: '高', MEDIUM: '中', LOW: '低', UNKNOWN: '未知' } as Record<string, string>)[quality] ?? '未知';
}

export function formatDecimal(value?: string | null, suffix = ''): string {
  if (value == null || value === '') return '—';
  const [integerPart, fractionPart] = value.split('.');
  const negative = integerPart.startsWith('-');
  const digits = negative ? integerPart.slice(1) : integerPart;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${negative ? '-' : ''}${grouped}${fractionPart ? `.${fractionPart}` : ''}${suffix}`;
}

export function formatPercent(value?: string | null): string {
  if (value == null || value === '') return '—';
  const percent = Number(value) * 100;
  return Number.isFinite(percent) ? `${percent.toFixed(2)}%` : value;
}
