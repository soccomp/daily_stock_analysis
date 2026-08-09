import type React from 'react';
import { AlertTriangle, BookOpen, BriefcaseBusiness, FileCheck2, ShieldCheck, WalletCards } from 'lucide-react';
import { Badge, Card, Collapsible, Drawer, InlineAlert, Loading } from '../common';
import type {
  DecisionScorecardDetail,
  PortfolioSnapshotView,
} from '../../types/investmentDecisions';
import { formatDateTime } from '../../utils/format';
import {
  actionPresentation,
  blockReasonLabel,
  dataQualityLabel,
  executionLabel,
  formatDecimal,
  formatPercent,
  reconciliationLabel,
} from './presentation';

type DecisionScorecardDrawerProps = {
  isOpen: boolean;
  detail: DecisionScorecardDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export const DecisionScorecardDrawer: React.FC<DecisionScorecardDrawerProps> = ({
  isOpen,
  detail,
  loading,
  error,
  onClose,
}) => (
  <Drawer
    isOpen={isOpen}
    onClose={onClose}
    title={detail ? `${detail.investmentDecision.symbol} 决策档案` : '决策档案'}
    eyebrow="决策档案"
    width="max-w-3xl"
  >
    {loading ? <Loading label="正在读取决策档案" /> : null}
    {error ? (
      <InlineAlert
        variant="danger"
        title="决策档案读取失败"
        message={error}
      />
    ) : null}
    {!loading && !error && detail ? <DecisionArchive detail={detail} /> : null}
  </Drawer>
);

const DecisionArchive: React.FC<{ detail: DecisionScorecardDetail }> = ({ detail }) => {
  const research = detail.researchBundle;
  const decision = detail.investmentDecision;
  const policy = detail.riskPolicy;
  const mandate = detail.executionMandate;
  const result = detail.executionResults.at(-1);
  const action = actionPresentation[decision.action];
  const execution = executionLabel(result?.status ?? (
    detail.executionDiagnostics.executionState as Parameters<typeof executionLabel>[0]
  ));
  const reconciliation = reconciliationLabel(result?.reconciliationStatus);
  const blockReason = blockReasonLabel(result?.blockReason);

  return (
    <div className="space-y-5 pb-4">
      <ArchiveSection icon={<BookOpen className="h-4 w-4" />} title="研究依据">
        <FactGrid
          facts={[
            ['市场环境', research.marketRegime],
            ['行业观点', research.industryView],
            ['基本面', research.fundamentalView],
            ['技术面', research.technicalView],
            ['估值', research.valuationView],
            ['情报', research.intelView],
            ['资金面', research.capitalFlowView],
          ]}
        />
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Scenario title="乐观情景" text={research.bullCase} />
          <Scenario title="基准情景" text={research.baseCase} />
          <Scenario title="谨慎情景" text={research.bearCase} />
        </div>
        <ListFacts title="催化因素" values={research.catalysts} empty="暂无明确催化因素" />
        <ListFacts title="风险因素" values={research.riskFactors} empty="暂无已记录风险因素" />
        <div className="mt-4 flex flex-wrap gap-2">
          <Badge variant="info">研究置信度 {formatPercent(research.confidence)}</Badge>
          <Badge variant="default">数据质量 {dataQualityLabel(research.dataQuality)}</Badge>
        </div>
      </ArchiveSection>

      <ArchiveSection icon={<WalletCards className="h-4 w-4" />} title="决策前账户">
        <SnapshotFacts snapshot={detail.portfolioSnapshotA} symbol={decision.symbol} />
      </ArchiveSection>

      <ArchiveSection icon={<ShieldCheck className="h-4 w-4" />} title="风险约束">
        <FactGrid
          facts={[
            ['单一持仓上限', formatPercent(policy.maxSinglePositionWeight)],
            ['总敞口上限', formatPercent(policy.maxTotalExposure)],
            ['最低现金比例', formatPercent(policy.minCashWeight)],
            ['单笔风险预算', formatPercent(policy.riskBudgetPerTrade)],
            ['最大同时持仓数', String(policy.maxConcurrentPositions)],
            ['止损要求', policy.stopRequired ? '必须设置' : '不强制'],
            ['生效时间', formatDateTime(policy.effectiveFrom)],
            ['失效时间', policy.effectiveUntil ? formatDateTime(policy.effectiveUntil) : '持续有效'],
          ]}
        />
        <p className="mt-4 text-xs text-muted-text">该约束为当时决策所用的只读版本，不能在此修改。</p>
      </ArchiveSection>

      <ArchiveSection icon={<FileCheck2 className="h-4 w-4" />} title="投资决策">
        <div className="flex flex-wrap gap-2">
          <Badge variant={action.variant} size="md">{action.label}</Badge>
          <Badge variant="default">有效至 {formatDateTime(decision.validUntil)}</Badge>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Metric label="当前数量" value={`${decision.currentQuantity} 股`} />
          <Metric label="目标数量" value={`${decision.targetQuantity} 股`} />
          <Metric label="本次变化" value={`${decision.deltaQuantity} 股`} />
          <Metric label="目标权重" value={formatPercent(decision.targetWeight)} />
          <Metric label="预期收益" value={formatPercent(decision.expectedReturn)} />
          <Metric label="预期风险" value={formatPercent(decision.expectedRisk)} />
        </div>
        <Narrative title="决策理由" text={decision.rationale} />
        <Narrative title="风险理由" text={decision.riskReasoning} />
      </ArchiveSection>

      <ArchiveSection icon={<BriefcaseBusiness className="h-4 w-4" />} title="执行情况">
        {decision.action === 'HOLD' ? (
          <InlineAlert variant="info" message="本轮无需交易。" />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={execution.variant}>{execution.label}</Badge>
              {reconciliation ? <Badge variant={reconciliation.variant}>{reconciliation.label}</Badge> : null}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Metric label="决策数量" value={`${decision.deltaQuantity} 股`} />
              <Metric label="请求数量" value={result ? `${result.requestedQuantity} 股` : '—'} />
              <Metric label="提交数量" value={result ? `${result.submittedQuantity} 股` : '—'} />
              <Metric label="成交数量" value={result ? `${result.filledQuantity} 股` : '—'} />
              <Metric label="剩余数量" value={result ? `${result.remainingQuantity} 股` : '—'} />
              <Metric label="限价" value={mandate ? formatDecimal(mandate.limitPrice, ' CNY') : '—'} />
              <Metric label="成交均价" value={formatDecimal(result?.averageFillPrice, result?.averageFillPrice ? ' CNY' : '')} />
              <Metric label="费用" value={result ? formatDecimal(result.fees, ' CNY') : '—'} />
              <Metric label="滑点" value={result?.slippageBps == null ? '—' : `${result.slippageBps} bps`} />
            </div>
            {blockReason || result?.brokerReason ? (
              <InlineAlert
                className="mt-4"
                variant={result?.status === 'BROKER_REJECTED' ? 'danger' : 'warning'}
                title="执行说明"
                message={blockReason ?? result?.brokerReason ?? '执行条件未满足'}
              />
            ) : null}
            {result?.status === 'UNKNOWN' ? (
              <InlineAlert
                className="mt-4"
                variant="warning"
                title="状态仍待确认"
                message="系统正在等待账户事实核对，不会自动再次提交。"
              />
            ) : null}
          </>
        )}
      </ArchiveSection>

      <ArchiveSection icon={<AlertTriangle className="h-4 w-4" />} title="决策后账户">
        {detail.portfolioSnapshotB ? (
          <SnapshotFacts snapshot={detail.portfolioSnapshotB} symbol={decision.symbol} />
        ) : (
          <p className="text-sm text-secondary-text">尚无决策后账户快照</p>
        )}
      </ArchiveSection>

      <Collapsible title="技术详情">
        <div className="space-y-2 break-all font-mono text-xs text-secondary-text">
          <p>decision_id: {decision.decisionId}</p>
          <p>decision_cycle_id: {decision.decisionCycleId}</p>
          <p>scorecard_hash: {detail.scorecardHash}</p>
          <p>snapshot_a: {detail.portfolioSnapshotA.snapshotId}</p>
          <p>snapshot_a_hash: {detail.portfolioSnapshotA.contentHash}</p>
          <p>policy: {policy.policyId}@{policy.policyVersion}</p>
          {mandate ? <p>mandate_id: {mandate.mandateId}</p> : null}
          {result ? <p>result_id: {result.resultId}</p> : null}
          {detail.portfolioSnapshotB ? <p>snapshot_b: {detail.portfolioSnapshotB.snapshotId}</p> : null}
        </div>
      </Collapsible>
    </div>
  );
};

const ArchiveSection: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({ icon, title, children }) => (
  <Card className="border-border/60" padding="md">
    <div className="mb-4 flex items-center gap-2 text-foreground">
      <span className="text-cyan">{icon}</span>
      <h3 className="font-semibold">{title}</h3>
    </div>
    {children}
  </Card>
);

const FactGrid: React.FC<{ facts: Array<[string, string]> }> = ({ facts }) => (
  <dl className="grid gap-x-6 gap-y-4 md:grid-cols-2">
    {facts.map(([label, value]) => (
      <div key={label}>
        <dt className="text-xs text-muted-text">{label}</dt>
        <dd className="mt-1 text-sm leading-6 text-foreground">{value || '—'}</dd>
      </div>
    ))}
  </dl>
);

const Scenario: React.FC<{ title: string; text: string }> = ({ title, text }) => (
  <div className="rounded-xl border border-border/50 bg-elevated/45 p-3">
    <p className="text-xs font-medium text-muted-text">{title}</p>
    <p className="mt-2 text-sm leading-6 text-foreground">{text}</p>
  </div>
);

const ListFacts: React.FC<{ title: string; values: string[]; empty: string }> = ({ title, values, empty }) => (
  <div className="mt-4">
    <p className="text-xs text-muted-text">{title}</p>
    {values.length ? (
      <ul className="mt-2 space-y-1.5 text-sm text-foreground">
        {values.map((value) => <li key={value}>• {value}</li>)}
      </ul>
    ) : <p className="mt-2 text-sm text-secondary-text">{empty}</p>}
  </div>
);

const Metric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-xl border border-border/50 bg-elevated/45 px-3 py-3">
    <p className="text-xs text-muted-text">{label}</p>
    <p className="mt-1 font-mono text-sm font-semibold text-foreground">{value}</p>
  </div>
);

const Narrative: React.FC<{ title: string; text: string }> = ({ title, text }) => (
  <div className="mt-4">
    <p className="text-xs text-muted-text">{title}</p>
    <p className="mt-1 text-sm leading-6 text-foreground">{text}</p>
  </div>
);

const SnapshotFacts: React.FC<{ snapshot: PortfolioSnapshotView; symbol: string }> = ({ snapshot, symbol }) => {
  const position = snapshot.positions.find((item) => item.symbol === symbol);
  const reconciliation = reconciliationLabel(snapshot.reconciliationStatus);
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2">
        <Badge variant="default">{snapshot.accountMode === 'SIMULATION' ? '模拟账户' : snapshot.accountMode}</Badge>
        {reconciliation ? <Badge variant={reconciliation.variant}>{reconciliation.label}</Badge> : null}
      </div>
      <FactGrid
        facts={[
          ['账户权益', formatDecimal(snapshot.equity, ' CNY')],
          ['现金', formatDecimal(snapshot.cash, ' CNY')],
          ['可用资金', formatDecimal(snapshot.availableCash, ' CNY')],
          ['相关股票数量', position ? `${position.quantity} 股` : '0 股'],
          ['持仓成本', position ? formatDecimal(position.avgCost, ' CNY') : '—'],
          ['持仓市值', position ? formatDecimal(position.marketValue, ' CNY') : '—'],
          ['快照时间', formatDateTime(snapshot.asOf)],
          ['事实来源', snapshot.authoritative && snapshot.readOnly ? '已连接账户（只读）' : '无法确认'],
        ]}
      />
    </>
  );
};
