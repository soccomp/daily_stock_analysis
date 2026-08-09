import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Clock3, FileSearch, RefreshCw, ShieldCheck, WalletCards } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { investmentDecisionsApi } from '../api/investmentDecisions';
import { getParsedApiError } from '../api/error';
import { DecisionCard } from '../components/investment-decisions/DecisionCard';
import { DecisionScorecardDrawer } from '../components/investment-decisions/DecisionScorecardDrawer';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Card,
  EmptyState,
  Input,
  Loading,
  PageHeader,
  Pagination,
  Select,
  StatusDot,
} from '../components/common';
import type {
  DecisionScorecardDetail,
  DecisionScorecardSummary,
  InvestmentAction,
  SingleBrainReadiness,
} from '../types/investmentDecisions';
import { formatDateTime } from '../utils/format';

const PAGE_SIZE = 10;
const CURRENT_MODE = 'SIMULATION_EXECUTION';

const InvestmentDecisionsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<DecisionScorecardSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [symbolDraft, setSymbolDraft] = useState('');
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState<InvestmentAction | ''>('');
  const [readiness, setReadiness] = useState<SingleBrainReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ReturnType<typeof getParsedApiError> | null>(null);
  const requestId = useRef(0);

  const selectedDecisionId = searchParams.get('decision');
  const [detail, setDetail] = useState<DecisionScorecardDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    document.title = '投资决策 - DSA';
  }, []);

  const loadPage = useCallback(async () => {
    const currentRequest = requestId.current + 1;
    requestId.current = currentRequest;
    setLoading(true);
    try {
      const [listResponse, readinessResponse] = await Promise.all([
        investmentDecisionsApi.list({
          page,
          pageSize: PAGE_SIZE,
          mode: CURRENT_MODE,
          symbol: symbol || undefined,
          action: action || undefined,
        }),
        investmentDecisionsApi.readiness(),
      ]);
      if (requestId.current !== currentRequest) return;
      setItems(listResponse.items);
      setTotal(listResponse.total);
      setReadiness(readinessResponse);
      setError(null);
    } catch (loadError) {
      if (requestId.current !== currentRequest) return;
      setError(getParsedApiError(loadError));
    } finally {
      if (requestId.current === currentRequest) setLoading(false);
    }
  }, [action, page, symbol]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  useEffect(() => {
    if (!selectedDecisionId) {
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError(null);
    void investmentDecisionsApi.get(selectedDecisionId)
      .then((item) => {
        if (active) setDetail(item);
      })
      .catch((loadError) => {
        if (!active) return;
        setDetail(null);
        setDetailError(getParsedApiError(loadError).message);
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedDecisionId]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const openDecision = (decisionId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('decision', decisionId);
    setSearchParams(next);
  };
  const closeDecision = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('decision');
    setSearchParams(next, { replace: true });
  };

  return (
    <AppPage>
      <div className="space-y-6">
        <PageHeader
          eyebrow="自动投资"
          title="投资决策"
          description="查看自动投资的决策、执行情况和账户变化。"
          actions={(
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void loadPage()}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </button>
          )}
        />

        <AutomaticInvestmentStatus readiness={readiness} loading={loading && !readiness} />

        <Card padding="md">
          <form
            className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_auto] md:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setSymbol(symbolDraft.trim().toUpperCase());
            }}
          >
            <Input
              label="股票代码"
              value={symbolDraft}
              placeholder="例如 600519"
              onChange={(event) => setSymbolDraft(event.target.value)}
            />
            <Select
              label="投资动作"
              value={action}
              onChange={(value) => {
                setPage(1);
                setAction(value as InvestmentAction | '');
              }}
              options={[
                { value: '', label: '全部动作' },
                { value: 'BUY', label: '买入' },
                { value: 'ADD', label: '加仓' },
                { value: 'HOLD', label: '持有' },
              ]}
            />
            <div className="flex gap-2">
              <button type="submit" className="btn-primary h-11 flex-1 px-5 md:flex-none">查询</button>
              {(symbol || action) ? (
                <button
                  type="button"
                  className="btn-secondary h-11 px-4"
                  onClick={() => {
                    setPage(1);
                    setSymbolDraft('');
                    setSymbol('');
                    setAction('');
                  }}
                >
                  清除
                </button>
              ) : null}
            </div>
          </form>
        </Card>

        {error ? <ApiErrorAlert error={error} /> : null}
        {loading ? <Loading label="正在读取投资决策" /> : null}
        {!loading && !error && items.length === 0 ? (
          <EmptyState
            icon={<FileSearch className="h-7 w-7" />}
            title="暂无投资决策"
            description="自动投资完成一次账户级决策后，将在这里显示只读决策档案。"
          />
        ) : null}
        {!loading && !error && items.length > 0 ? (
          <section aria-label="投资决策时间线" className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-foreground">决策时间线</h2>
                <p className="mt-1 text-sm text-secondary-text">共 {total} 条模拟交易决策</p>
              </div>
              <Badge variant="info">模拟交易</Badge>
            </div>
            {items.map((item) => (
              <DecisionCard key={item.decisionId} item={item} onOpen={openDecision} />
            ))}
            <Pagination
              className="pt-2"
              currentPage={page}
              totalPages={totalPages}
              onPageChange={setPage}
            />
          </section>
        ) : null}
      </div>

      <DecisionScorecardDrawer
        isOpen={Boolean(selectedDecisionId)}
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onClose={closeDecision}
      />
    </AppPage>
  );
};

const AutomaticInvestmentStatus: React.FC<{ readiness: SingleBrainReadiness | null; loading: boolean }> = ({ readiness, loading }) => {
  const running = Boolean(
    readiness?.featureEnabled
    && readiness.recurringScheduler.enabled
    && readiness.recurringScheduler.authorityCount === 1,
  );
  const needsAttention = Boolean(readiness?.featureEnabled && !running);
  const stateLabel = loading
    ? '正在确认'
    : running
      ? '运行中'
      : needsAttention
        ? '需要关注'
        : '未运行';
  const stateTone = running ? 'success' : needsAttention ? 'warning' : 'neutral';
  const lastRun = readiness?.latestCycle?.completedAt ?? readiness?.latestCycle?.scheduledFor;
  const pending = readiness?.simulationExecution?.pendingExecutionCount;
  const mode = readiness?.executionMode === CURRENT_MODE ? '模拟交易' : '未启用';

  const facts = useMemo(() => [
    { label: '自动投资', value: stateLabel, icon: Activity, tone: stateTone },
    { label: '交易模式', value: mode, icon: ShieldCheck, tone: 'info' },
    { label: '最近运行', value: formatDateTime(lastRun), icon: Clock3, tone: 'neutral' },
    { label: '下次预计运行', value: formatDateTime(readiness?.recurringScheduler.nextRunAt), icon: Clock3, tone: 'neutral' },
    { label: '待核对事项', value: pending == null ? '—' : `${pending} 项`, icon: FileSearch, tone: pending ? 'warning' : 'success' },
    { label: '最近账户快照', value: formatDateTime(readiness?.latestAuthoritativeSnapshot?.asOf), icon: WalletCards, tone: 'neutral' },
  ] as const, [lastRun, mode, pending, readiness?.latestAuthoritativeSnapshot?.asOf, readiness?.recurringScheduler.nextRunAt, stateLabel, stateTone]);

  return (
    <section aria-label="自动投资状态">
      <Card padding="md">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-foreground">自动投资状态</h2>
            <p className="mt-1 text-sm text-secondary-text">以下信息来自只读运行事实。</p>
          </div>
          <Badge variant={readiness?.executionAuthorization === 'ON' ? 'info' : 'default'}>
            执行授权：{readiness?.executionAuthorization === 'ON' ? '开启' : '关闭'}
          </Badge>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {facts.map(({ label, value, icon: Icon, tone }) => (
            <div key={label} className="rounded-xl border border-border/50 bg-elevated/40 px-4 py-3">
              <div className="flex items-center gap-2 text-xs text-muted-text">
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <StatusDot tone={tone} />
                <span className="text-sm font-medium text-foreground">{value}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </section>
  );
};

export default InvestmentDecisionsPage;
