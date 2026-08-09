import type React from 'react';
import { ArrowRight, FileText } from 'lucide-react';
import { Badge, Card } from '../common';
import type { DecisionScorecardSummary } from '../../types/investmentDecisions';
import { formatDateTime } from '../../utils/format';
import {
  actionPresentation,
  blockReasonLabel,
  executionLabel,
  formatPercent,
  reconciliationLabel,
} from './presentation';

type DecisionCardProps = {
  item: DecisionScorecardSummary;
  onOpen: (decisionId: string) => void;
};

export const DecisionCard: React.FC<DecisionCardProps> = ({ item, onOpen }) => {
  const action = actionPresentation[item.action];
  const execution = executionLabel(item.executionStatus);
  const reconciliation = reconciliationLabel(item.reconciliationStatus);
  const reason = blockReasonLabel(item.blockReason) ?? item.brokerReason;

  return (
    <Card className="overflow-hidden" padding="none">
      <div className="border-b border-border/50 px-5 py-4 md:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={action.variant} size="md">{action.label}</Badge>
              <span className="font-mono text-lg font-semibold text-foreground">{item.symbol}</span>
              <span className="text-sm text-muted-text">{item.market}</span>
            </div>
            <p className="mt-2 text-xs text-muted-text">{formatDateTime(item.createdAt)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default">决策置信度 {formatPercent(item.confidence)}</Badge>
            <Badge variant={execution.variant}>{execution.label}</Badge>
            {reconciliation ? <Badge variant={reconciliation.variant}>{reconciliation.label}</Badge> : null}
          </div>
        </div>
      </div>

      <div className="grid gap-5 px-5 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:px-6">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-secondary-text">
            <span>当前 <strong className="text-foreground">{item.currentQuantity}</strong> 股</span>
            <ArrowRight className="h-4 w-4 text-muted-text" aria-hidden="true" />
            <span>目标 <strong className="text-foreground">{item.targetQuantity}</strong> 股</span>
            <span className="rounded-lg bg-elevated px-2.5 py-1 text-xs text-secondary-text">
              本次变化 {item.deltaQuantity} 股
            </span>
          </div>

          {item.action === 'HOLD' ? (
            <p className="text-sm font-medium text-foreground">继续持有，本轮无需交易。</p>
          ) : (
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <QuantityFact label="决策数量" value={item.deltaQuantity} />
              <QuantityFact label="请求数量" value={item.requestedQuantity} />
              <QuantityFact label="提交数量" value={item.submittedQuantity} />
              <QuantityFact label="成交数量" value={item.filledQuantity} />
            </div>
          )}

          <p className="line-clamp-2 text-sm leading-6 text-secondary-text">{item.rationale}</p>
          {reason ? (
            <p className="text-sm text-warning">执行说明：{reason}</p>
          ) : null}
          {item.executionStatus === 'UNKNOWN' ? (
            <p className="text-sm font-medium text-warning">交易状态仍待核对，系统不会盲目重试。</p>
          ) : null}
        </div>

        <div className="flex items-end md:justify-end">
          <button
            type="button"
            className="btn-secondary inline-flex w-full items-center justify-center gap-2 md:w-auto"
            onClick={() => onOpen(item.decisionId)}
            aria-label={`查看 ${item.symbol} 决策档案`}
          >
            <FileText className="h-4 w-4" />
            查看决策档案
          </button>
        </div>
      </div>
    </Card>
  );
};

const QuantityFact: React.FC<{ label: string; value?: number | null }> = ({ label, value }) => (
  <div className="rounded-xl border border-border/50 bg-elevated/45 px-3 py-2.5">
    <p className="text-xs text-muted-text">{label}</p>
    <p className="mt-1 font-mono font-semibold text-foreground">{value == null ? '—' : `${value} 股`}</p>
  </div>
);
