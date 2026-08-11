import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Microscope,
  ShieldCheck,
  WalletCards,
} from 'lucide-react';
import { investmentDecisionsApi } from '../../api/investmentDecisions';
import { portfolioApi } from '../../api/portfolio';
import type { StockBarItem, TaskInfo } from '../../types/analysis';
import type { DecisionScorecardSummary, SingleBrainReadiness } from '../../types/investmentDecisions';
import type { ConnectedPortfolioSnapshot } from '../../types/portfolio';
import { formatDateTime } from '../../utils/format';
import {
  actionPresentation,
  blockReasonLabel,
  dataQualityLabel,
  executionLabel,
  reconciliationLabel,
} from '../investment-decisions/presentation';
import { Badge, Card, EmptyState, InlineAlert } from '../common';

const SHANGHAI_TIME_ZONE = 'Asia/Shanghai';
const TOP_HOLDINGS_LIMIT = 6;
const TODAY_DECISIONS_LIMIT = 5;
const TODAY_RESEARCH_LIMIT = 8;

type ResourceState<T> = { data: T | null; loading: boolean; error: string | null };

export interface DailyOverviewProps {
  researchItems: StockBarItem[];
  researchLoading: boolean;
  researchUnavailable: boolean;
  activeTasks: TaskInfo[];
  watchlistCovered: number;
  watchlistTotal: number;
  latestMarketReviewAt?: string | null;
  onOpenResearch: (item: StockBarItem) => void;
  onOpenWorkbench: () => void;
  onNavigate: (path: string) => void;
}

type TimelineItem = {
  id: string;
  occurredAt: string;
  title: string;
  detail: string;
  tone: 'neutral' | 'info' | 'success' | 'warning' | 'danger';
};

function shanghaiDateKey(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', { timeZone: SHANGHAI_TIME_ZONE }).format(date);
}

function isToday(value?: string | null): boolean {
  return Boolean(value && shanghaiDateKey(value) === shanghaiDateKey(new Date()));
}

function formatCanonicalMoney(value: string, currency: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return `${currency} ${value}`;
  return `${currency} ${number.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  })}`;
}

function formatQuantity(value?: number | null): string {
  return value == null ? '—' : `${value.toLocaleString('zh-CN')} 股`;
}

function runtimePresentation(readiness: SingleBrainReadiness | null, error: string | null) {
  if (error) return { label: '需要关注', variant: 'warning' as const, description: '暂时无法确认自动投资运行状态。' };
  if (!readiness || !readiness.featureEnabled || !readiness.recurringScheduler.enabled) {
    return { label: '未运行', variant: 'default' as const, description: '自动投资当前未启用。' };
  }
  if (readiness.recurringScheduler.authorityCount !== 1 || readiness.latestCycle?.status === 'FAILED') {
    return { label: '需要关注', variant: 'warning' as const, description: '运行状态存在需要核对的事项。' };
  }
  if (!isHealthySimulationAuthorization(readiness)) {
    return { label: '需要关注', variant: 'warning' as const, description: '模拟执行授权或运行模式需要核对。' };
  }
  return { label: '运行中', variant: 'success' as const, description: '系统按既定周期进行研究与投资决策。' };
}

function isHealthySimulationAuthorization(readiness: SingleBrainReadiness): boolean {
  return readiness.executionMode === 'SIMULATION_EXECUTION'
    && readiness.executionAuthorization === 'ON'
    && readiness.recurringScheduler.mode === 'M3_SIMULATION_EXECUTION_ONLY';
}

function authorizationPresentation(readiness: SingleBrainReadiness | null) {
  if (!readiness) return { label: '状态待确认', variant: 'warning' as const };
  if (readiness.featureEnabled && readiness.recurringScheduler.enabled) {
    return isHealthySimulationAuthorization(readiness)
      ? { label: '模拟执行授权：开启', variant: 'success' as const }
      : { label: '执行授权：状态待确认', variant: 'warning' as const };
  }
  return readiness.executionAuthorization === 'OFF'
    ? { label: '执行授权：关闭', variant: 'default' as const }
    : { label: '执行授权：状态待确认', variant: 'warning' as const };
}

function cycleStatusLabel(status?: string | null): string {
  if (!status) return '暂无运行记录';
  return ({
    COMPLETED: '已完成',
    FAILED: '运行失败',
    BLOCKED: '本轮未生成决策',
    RUNNING: '运行中',
    PENDING: '等待运行',
  } as Record<string, string>)[status] ?? '状态待确认';
}

function researchView(item: StockBarItem): string {
  return item.actionLabel || item.operationAdvice || '研究观点待查看';
}

function decisionExecutionSummary(item: DecisionScorecardSummary): string {
  if (item.action === 'HOLD') return '继续持有，本轮无需交易';
  if (item.executionStatus === 'UNKNOWN') return '状态待确认，系统不会盲目重试';
  const reason = blockReasonLabel(item.blockReason) ?? item.brokerReason;
  if (reason) return reason;
  if ((item.submittedQuantity ?? 0) > 0) return `已提交 ${formatQuantity(item.submittedQuantity)}`;
  if (item.executionStatus === 'NOT_AUTHORIZED') return '本轮仅观察，未授权执行';
  if (item.executionStatus === 'NOT_APPLICABLE') return '本轮无需交易';
  return executionLabel(item.executionStatus).label;
}

function mandateSummary(item: DecisionScorecardSummary): string {
  if (item.action === 'HOLD') return '未生成（本轮无需交易）';
  if (item.requestedQuantity != null) return `已生成 · ${formatQuantity(item.requestedQuantity)}`;
  return '未记录';
}

function brokerSubmissionSummary(item: DecisionScorecardSummary): string {
  if (item.executionStatus === 'UNKNOWN') {
    return (item.submittedQuantity ?? 0) > 0
      ? `状态待确认 · 记录数量 ${formatQuantity(item.submittedQuantity)}`
      : '状态待确认';
  }
  return (item.submittedQuantity ?? 0) > 0 ? `已提交 ${formatQuantity(item.submittedQuantity)}` : '未提交';
}

function decisionTimelineTone(item: DecisionScorecardSummary): TimelineItem['tone'] {
  if (item.action === 'HOLD') return 'neutral';
  if (item.executionStatus === 'UNKNOWN' || item.executionStatus === 'BLOCKED') return 'warning';
  if (item.executionStatus === 'FILLED') return 'success';
  if (item.executionStatus === 'ACCEPTED' || item.executionStatus === 'ACTIVE' || item.executionStatus === 'PARTIALLY_FILLED') return 'info';
  if (item.executionStatus === 'BROKER_REJECTED') return 'danger';
  return 'neutral';
}

function timelineDotClass(tone: TimelineItem['tone']): string {
  if (tone === 'danger') return 'bg-danger';
  if (tone === 'warning') return 'bg-warning';
  if (tone === 'success') return 'bg-success';
  if (tone === 'info') return 'bg-cyan';
  return 'bg-muted-text';
}

const SectionHeading: React.FC<{
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}> = ({ icon, title, description, action }) => (
  <div className="mb-4 flex items-start justify-between gap-4">
    <div className="flex min-w-0 items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-cyan/20 bg-cyan/10 text-cyan">{icon}</span>
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-xs leading-5 text-secondary-text">{description}</p>
      </div>
    </div>
    {action ? <div className="shrink-0">{action}</div> : null}
  </div>
);

const DailyOverview: React.FC<DailyOverviewProps> = ({
  researchItems,
  researchLoading,
  researchUnavailable,
  activeTasks,
  watchlistCovered,
  watchlistTotal,
  latestMarketReviewAt,
  onOpenResearch,
  onOpenWorkbench,
  onNavigate,
}) => {
  const [portfolio, setPortfolio] = useState<ResourceState<ConnectedPortfolioSnapshot>>({ data: null, loading: true, error: null });
  const [decisions, setDecisions] = useState<ResourceState<DecisionScorecardSummary[]>>({ data: null, loading: true, error: null });
  const [readiness, setReadiness] = useState<ResourceState<SingleBrainReadiness>>({ data: null, loading: true, error: null });

  useEffect(() => {
    let active = true;
    portfolioApi.getConnectedSnapshot()
      .then((data) => active && setPortfolio({ data, loading: false, error: null }))
      .catch((error: unknown) => active && setPortfolio({ data: null, loading: false, error: error instanceof Error ? error.message : '权威账户快照暂时不可用' }));
    investmentDecisionsApi.list({ page: 1, pageSize: 20, mode: 'SIMULATION_EXECUTION' })
      .then((data) => active && setDecisions({ data: data.items.filter((item) => item.mode === 'SIMULATION_EXECUTION'), loading: false, error: null }))
      .catch((error: unknown) => active && setDecisions({ data: null, loading: false, error: error instanceof Error ? error.message : '投资决策暂时不可用' }));
    investmentDecisionsApi.readiness()
      .then((data) => active && setReadiness({ data, loading: false, error: null }))
      .catch((error: unknown) => active && setReadiness({ data: null, loading: false, error: error instanceof Error ? error.message : '运行状态暂时不可用' }));
    return () => { active = false; };
  }, []);

  const todayDecisions = useMemo(
    () => (decisions.data ?? []).filter((item) => isToday(item.createdAt))
      .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))
      .slice(0, TODAY_DECISIONS_LIMIT),
    [decisions.data],
  );
  const allTodayResearch = useMemo(
    () => researchItems.filter((item) => isToday(item.lastAnalysisTime))
      .sort((left, right) => Date.parse(right.lastAnalysisTime ?? '') - Date.parse(left.lastAnalysisTime ?? '')),
    [researchItems],
  );
  const todayResearch = useMemo(() => allTodayResearch.slice(0, TODAY_RESEARCH_LIMIT), [allTodayResearch]);
  const topHoldings = useMemo(
    () => [...(portfolio.data?.positions ?? [])].sort((left, right) => {
      const marketValueDifference = Number(right.marketValue) - Number(left.marketValue);
      return marketValueDifference || `${left.market}:${left.symbol}`.localeCompare(`${right.market}:${right.symbol}`);
    }).slice(0, TOP_HOLDINGS_LIMIT),
    [portfolio.data?.positions],
  );
  const runningTasks = activeTasks.filter((task) => task.status === 'pending' || task.status === 'processing');
  const runtime = runtimePresentation(readiness.data, readiness.error);
  const authorization = authorizationPresentation(readiness.data);

  const attentionItems = useMemo(() => {
    const items: string[] = [];
    if (portfolio.error) items.push('已连接账户快照暂时不可用');
    if (portfolio.data?.reconciliationStatus && portfolio.data.reconciliationStatus !== 'RECONCILED') {
      items.push(`账户快照${reconciliationLabel(portfolio.data.reconciliationStatus)?.label ?? '需要核对'}`);
    }
    if (portfolio.data && ['LOW', 'UNKNOWN'].includes(portfolio.data.dataQuality)) items.push('账户数据质量需要关注');
    if (readiness.error) items.push('自动投资运行状态暂时不可用');
    if (readiness.data && authorization.variant === 'warning') items.push('模拟执行授权或运行模式需要核对');
    if (readiness.data?.recurringScheduler.authorityCount !== undefined && readiness.data.recurringScheduler.authorityCount !== 1) items.push('自动投资调度状态需要核对');
    if (readiness.data?.latestCycle?.status === 'FAILED') items.push('最近一轮自动投资运行失败');
    if (researchUnavailable) items.push('今日研究记录暂时不可用');
    if (todayDecisions.some((item) => item.executionStatus === 'UNKNOWN')) items.push('存在交易状态待确认的投资决策');
    const pendingCount = readiness.data?.simulationExecution?.pendingExecutionCount ?? 0;
    if (pendingCount > 0) items.push(`有 ${pendingCount} 项执行事实待核对`);
    return [...new Set(items)];
  }, [authorization.variant, portfolio.data, portfolio.error, readiness.data, readiness.error, researchUnavailable, todayDecisions]);

  const timeline = useMemo<TimelineItem[]>(() => {
    const items: TimelineItem[] = todayResearch.flatMap((item) => item.lastAnalysisTime ? [{
      id: `research:${item.id}`,
      occurredAt: item.lastAnalysisTime,
      title: `${item.stockName || item.stockCode}：研究完成`,
      detail: `研究观点：${researchView(item)}`,
      tone: 'info' as const,
    }] : []);
    for (const item of todayDecisions) {
      items.push({
        id: `decision:${item.decisionId}`,
        occurredAt: item.createdAt,
        title: `${item.symbol}：Brain 决定${actionPresentation[item.action].label}`,
        detail: decisionExecutionSummary(item),
        tone: decisionTimelineTone(item),
      });
    }
    if (portfolio.data && isToday(portfolio.data.asOf)) items.push({
      id: `snapshot:${portfolio.data.snapshotId}`,
      occurredAt: portfolio.data.asOf,
      title: '已连接账户事实已更新',
      detail: `核对状态：${reconciliationLabel(portfolio.data.reconciliationStatus)?.label ?? '状态待确认'}`,
      tone: portfolio.data.reconciliationStatus === 'RECONCILED' ? 'success' : 'warning',
    });
    if (readiness.data?.latestCycle?.completedAt && isToday(readiness.data.latestCycle.completedAt)) items.push({
      id: `cycle:${readiness.data.latestCycle.scheduledFor ?? readiness.data.latestCycle.completedAt}`,
      occurredAt: readiness.data.latestCycle.completedAt,
      title: '自动投资完成本轮运行',
      detail: `运行结果：${cycleStatusLabel(readiness.data.latestCycle.status)}`,
      tone: readiness.data.latestCycle.status === 'FAILED' ? 'danger' : 'success',
    });
    return items.filter((item) => !Number.isNaN(Date.parse(item.occurredAt)))
      .sort((left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt)).slice(0, 12);
  }, [portfolio.data, readiness.data, todayDecisions, todayResearch]);

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-10" data-testid="daily-overview">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(22rem,0.85fr)]">
        <Card className="order-2 overflow-hidden xl:order-1" padding="lg">
          <SectionHeading icon={<WalletCards className="h-4 w-4" />} title="账户概览" description="来自已连接账户的权威、只读事实，不与手工账户合并。" action={portfolio.data ? <Badge variant="info">{portfolio.data.currency}</Badge> : undefined} />
          {portfolio.loading ? <EmptyState title="正在读取账户快照" description="账户事实确认后将在这里显示。" /> : null}
          {!portfolio.loading && portfolio.error ? <InlineAlert variant="warning" title="已连接账户暂时不可用" message="无法确认权威账户事实，因此不会显示零余额，也不会回退到手工账户。" /> : null}
          {portfolio.data ? <>
            <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-3">
              {[
                ['账户权益', portfolio.data.equity], ['现金合计', portfolio.data.cash], ['可用现金', portfolio.data.availableCash],
                ['冻结现金', portfolio.data.reservedCash], ['已实现盈亏', portfolio.data.realizedPnl], ['未实现盈亏', portfolio.data.unrealizedPnl],
              ].map(([label, value]) => <div key={label} className="min-w-0"><p className="text-xs text-muted-text">{label}</p><p className="mt-1 truncate font-mono text-sm font-semibold text-foreground sm:text-[1rem]">{formatCanonicalMoney(value, portfolio.data!.currency)}</p></div>)}
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border/50 pt-4 text-xs text-secondary-text">
              <Badge variant={portfolio.data.reconciliationStatus === 'RECONCILED' ? 'success' : 'warning'}>{reconciliationLabel(portfolio.data.reconciliationStatus)?.label ?? '状态待确认'}</Badge>
              <Badge variant={portfolio.data.dataQuality === 'HIGH' ? 'success' : 'warning'}>数据质量 · {dataQualityLabel(portfolio.data.dataQuality)}</Badge>
              <span>快照时间 · {formatDateTime(portfolio.data.asOf)}</span><span>持仓 · {portfolio.data.positions.length} 项</span>
            </div>
          </> : null}
        </Card>

        <Card className="order-1 overflow-hidden xl:order-2" padding="lg">
          <SectionHeading icon={<Activity className="h-4 w-4" />} title="自动投资状态" description="展示当前模拟运行事实，不提供任何执行控制。" action={<Badge variant={runtime.variant}>{runtime.label}</Badge>} />
          {readiness.loading ? <EmptyState title="正在确认运行状态" description="稍候显示最近运行与下一次预计时间。" /> : null}
          {!readiness.loading ? <div className="space-y-4">
            <p className="text-sm text-secondary-text">{runtime.description}</p>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <RuntimeFact label="当前模式" value={readiness.data?.executionMode?.includes('SIMULATION') ? '模拟交易' : '状态待确认'} />
              <RuntimeFact label="最近结果" value={cycleStatusLabel(readiness.data?.latestCycle?.status)} />
              <RuntimeFact label="最近运行" value={readiness.data?.latestCycle?.completedAt ? formatDateTime(readiness.data.latestCycle.completedAt) : '暂无记录'} />
              <RuntimeFact label="下次预计" value={readiness.data?.recurringScheduler.nextRunAt ? formatDateTime(readiness.data.recurringScheduler.nextRunAt) : '尚未登记'} />
              <RuntimeFact label="待核对事项" value={`${readiness.data?.simulationExecution?.pendingExecutionCount ?? 0} 项`} />
              <RuntimeFact label="最近账户快照" value={readiness.data?.latestAuthoritativeSnapshot?.asOf ? formatDateTime(readiness.data.latestAuthoritativeSnapshot.asOf) : '暂无记录'} />
            </dl>
            <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${authorization.variant === 'success' ? 'border-success/15 bg-success/5 text-success' : authorization.variant === 'warning' ? 'border-warning/20 bg-warning/5 text-warning' : 'border-border/60 bg-elevated/35 text-secondary-text'}`}><ShieldCheck className="h-4 w-4 shrink-0" />{authorization.label}</div>
          </div> : null}
        </Card>
      </div>

      <Card padding="md">
        <SectionHeading icon={attentionItems.length === 0 ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />} title="需要关注" description="只列出已有事实支持的异常、待核对或不可用状态。" />
        {attentionItems.length === 0 ? <div className="flex items-center gap-3 rounded-xl border border-success/15 bg-success/5 px-4 py-3 text-sm text-success"><CheckCircle2 className="h-4 w-4 shrink-0" />目前没有需要处理的事项</div> : <div className="grid gap-2 md:grid-cols-2">{attentionItems.map((item) => <div key={item} className="flex items-start gap-2 rounded-xl border border-warning/20 bg-warning/5 px-3 py-2.5 text-sm text-warning"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{item}</div>)}</div>}
      </Card>

      <Card padding="lg">
        <SectionHeading icon={<BriefcaseBusiness className="h-4 w-4" />} title="当前持仓" description="按市值稳定排序，市场与股票代码共同确定一项持仓。" action={portfolio.data ? <button type="button" className="btn-secondary text-xs" onClick={() => onNavigate('/portfolio?account=connected')}>查看全部持仓</button> : undefined} />
        {portfolio.data && topHoldings.length > 0 ? <div className="space-y-2">
          {topHoldings.map((position) => <div key={`${position.market}:${position.symbol}`} data-testid={`overview-holding-${position.market}-${position.symbol}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-xl border border-border/50 bg-elevated/35 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_repeat(3,minmax(7rem,auto))] sm:items-center">
            <div className="min-w-0"><div className="flex items-center gap-2"><Badge variant="default">{position.market}</Badge><span className="font-mono font-semibold text-foreground">{position.symbol}</span></div><p className="mt-1 text-xs text-muted-text">可用 {formatQuantity(position.availableQuantity)}</p></div>
            <HoldingFact label="数量" value={formatQuantity(position.quantity)} />
            <HoldingFact label="最新价" value={formatCanonicalMoney(position.lastPrice, portfolio.data!.currency)} className="hidden sm:block" />
            <HoldingFact label="市值 / 未实现盈亏" value={`${formatCanonicalMoney(position.marketValue, portfolio.data!.currency)} · ${formatCanonicalMoney(position.unrealizedPnl, portfolio.data!.currency)}`} className="col-span-2 sm:col-span-1" />
          </div>)}
          <p className="pt-1 text-xs text-muted-text">共 {portfolio.data.positions.length} 项持仓</p>
        </div> : null}
        {portfolio.data && topHoldings.length === 0 ? <EmptyState title="当前没有权威持仓" description="该事实来自已连接账户快照。" /> : null}
        {!portfolio.loading && !portfolio.data ? <EmptyState title="无法显示当前持仓" description="权威账户快照不可用时不会显示手工账户作为替代。" /> : null}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="order-4 xl:order-none" padding="lg">
          <SectionHeading icon={<BriefcaseBusiness className="h-4 w-4" />} title="今日投资决策" description="仅展示 Brain 的最终投资决策与真实执行状态。" action={<button type="button" className="btn-secondary text-xs" onClick={() => onNavigate('/investment-decisions')}>全部决策</button>} />
          {decisions.loading ? <EmptyState title="正在读取投资决策" description="稍候显示今天的决策。" /> : null}
          {decisions.error ? <InlineAlert variant="warning" title="投资决策暂时不可用" message="账户与研究信息仍可独立查看。" /> : null}
          {!decisions.loading && !decisions.error && todayDecisions.length === 0 ? <EmptyState title="今天还没有投资决策" description="研究观点不会自动当作投资决策。" /> : null}
          <div className="space-y-2">{todayDecisions.map((item) => {
            const action = actionPresentation[item.action]; const execution = executionLabel(item.executionStatus);
            return <button key={item.decisionId} type="button" onClick={() => onNavigate(`/investment-decisions?decision=${encodeURIComponent(item.decisionId)}`)} className="w-full rounded-xl border border-border/50 bg-elevated/35 px-4 py-3 text-left transition-colors hover:border-cyan/30 hover:bg-elevated/60">
              <div className="flex flex-wrap items-center gap-2"><Badge variant={action.variant}>{action.label}</Badge><span className="font-mono font-semibold text-foreground">{item.market}:{item.symbol}</span><Badge data-testid={`overview-execution-${item.decisionId}`} variant={execution.variant}>{execution.label}</Badge><span className="ml-auto text-xs text-muted-text">{formatDateTime(item.createdAt)}</span></div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-secondary-text"><span>当前 {formatQuantity(item.currentQuantity)}</span><ArrowRight className="h-4 w-4" /><span>目标 {formatQuantity(item.targetQuantity)}</span><span>变化 {formatQuantity(item.deltaQuantity)}</span></div>
              <p className="mt-2 line-clamp-2 text-sm leading-6 text-secondary-text">{item.rationale}</p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-text"><span>执行指令：{mandateSummary(item)}</span><span>券商提交：{brokerSubmissionSummary(item)}</span></div>
              <p className={`mt-2 text-xs ${item.executionStatus === 'UNKNOWN' ? 'text-warning' : 'text-muted-text'}`}>执行状态：{decisionExecutionSummary(item)}</p>
            </button>;
          })}</div>
        </Card>

        <Card className="order-5 xl:order-none" padding="lg">
          <SectionHeading icon={<Microscope className="h-4 w-4" />} title="今日研究" description="研究解释资产与市场，不代表账户资本配置。" action={<button type="button" className="btn-secondary text-xs" onClick={onOpenWorkbench}>进入研究工作台</button>} />
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4"><RuntimeFact label="已完成分析" value={`${allTodayResearch.length} 项`} /><RuntimeFact label="正在分析" value={`${runningTasks.length} 项`} /><RuntimeFact label="观察列表覆盖" value={watchlistTotal > 0 ? `${watchlistCovered} / ${watchlistTotal}` : '暂无观察列表'} /><RuntimeFact label="最近市场复盘" value={latestMarketReviewAt ? formatDateTime(latestMarketReviewAt) : '暂无记录'} /></div>
          {researchLoading ? <EmptyState title="正在读取今日研究" description="研究记录加载不会影响账户事实。" /> : null}
          {researchUnavailable ? <InlineAlert variant="warning" title="今日研究暂时不可用" message="账户与投资决策仍可独立查看。" /> : null}
          {!researchLoading && !researchUnavailable && todayResearch.length === 0 ? <EmptyState title="今天还没有完成研究" description="新的研究完成后会出现在这里。" /> : null}
          <div className="space-y-2">{todayResearch.map((item) => <button key={`${item.id}:${item.stockCode}`} type="button" onClick={() => onOpenResearch(item)} className="w-full rounded-xl border border-border/50 bg-elevated/35 px-4 py-3 text-left transition-colors hover:border-cyan/30 hover:bg-elevated/60">
            <div className="flex flex-wrap items-center gap-2"><Badge variant="history">研究观点</Badge><span className="font-semibold text-foreground">{item.stockName || item.stockCode}</span><span className="font-mono text-xs text-muted-text">{item.stockCode}</span><span className="ml-auto text-xs text-muted-text">{item.lastAnalysisTime ? formatDateTime(item.lastAnalysisTime) : '时间待确认'}</span></div>
            <p className="mt-2 text-sm text-secondary-text">{researchView(item)}</p>{item.sentimentScore != null ? <p className="mt-1 text-xs text-muted-text">研究情绪分 {item.sentimentScore}</p> : null}
          </button>)}</div>
        </Card>
      </div>

      <Card padding="lg">
        <SectionHeading icon={<Clock3 className="h-4 w-4" />} title="今日动态" description="按已有时间戳排列事实；没有证据的事件不会出现在这里。" />
        {timeline.length === 0 ? <EmptyState title="今天还没有可确认的动态" description="账户、研究或决策事实更新后会显示在这里。" /> : <ol className="relative space-y-4 border-l border-border/70 pl-5">{timeline.map((item) => <li key={item.id} data-testid={`overview-timeline-${item.id.replace(':', '-')}`} data-tone={item.tone} className="relative"><span className={`absolute -left-[1.55rem] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${timelineDotClass(item.tone)}`} /><div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><time className="font-mono text-xs text-muted-text">{formatDateTime(item.occurredAt)}</time><p className="text-sm font-medium text-foreground">{item.title}</p></div><p className="mt-1 text-xs leading-5 text-secondary-text">{item.detail}</p></li>)}</ol>}
      </Card>
    </div>
  );
};

const RuntimeFact: React.FC<{ label: string; value: string }> = ({ label, value }) => <div className="rounded-xl border border-border/50 bg-elevated/35 px-3 py-2.5"><dt className="text-xs text-muted-text">{label}</dt><dd className="mt-1 text-sm font-medium text-foreground">{value}</dd></div>;
const HoldingFact: React.FC<{ label: string; value: string; className?: string }> = ({ label, value, className = '' }) => <div className={className}><p className="text-[11px] text-muted-text">{label}</p><p className="mt-1 text-xs font-medium text-foreground">{value}</p></div>;

export default DailyOverview;
