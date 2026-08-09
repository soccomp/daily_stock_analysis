import type React from 'react';
import { Badge, Card, EmptyState, InlineAlert } from '../common';
import type { ConnectedPortfolioSnapshot } from '../../types/portfolio';
import { formatDateTime } from '../../utils/format';

interface ConnectedPortfolioAccountViewProps {
  snapshot: ConnectedPortfolioSnapshot | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

function formatCanonicalMoney(value: string, currency: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return `${currency} ${value}`;
  return `${currency} ${amount.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  })}`;
}

function statusVariant(value: string): 'success' | 'warning' | 'danger' {
  if (value === 'RECONCILED' || value === 'HIGH') return 'success';
  if (value === 'UNKNOWN' || value === 'LOW') return 'danger';
  return 'warning';
}

const reconciliationLabels: Record<ConnectedPortfolioSnapshot['reconciliationStatus'], string> = {
  RECONCILED: '已核对',
  PENDING_RECONCILIATION: '待核对',
  DEGRADED: '核对受限',
  UNKNOWN: '状态待确认',
};

const dataQualityLabels: Record<ConnectedPortfolioSnapshot['dataQuality'], string> = {
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  UNKNOWN: '待确认',
};

const orderStateLabels = {
  ACCEPTED: '已接受',
  ACTIVE: '活动中',
  PARTIALLY_FILLED: '部分成交',
  UNKNOWN: '状态待确认',
} as const;

const ConnectedPortfolioAccountView: React.FC<ConnectedPortfolioAccountViewProps> = ({
  snapshot,
  loading,
  error,
  onRefresh,
}) => {
  if (!snapshot) {
    return (
      <Card padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">Athena 已连接账户</h2>
              <Badge variant="info">只读</Badge>
            </div>
            <p className="mt-1 text-xs text-secondary">
              账户事实不可确认时不会显示为零资产，也不会回退到 DSA 手工账本。
            </p>
          </div>
          <button type="button" className="btn-secondary text-sm" onClick={onRefresh} disabled={loading}>
            {loading ? '读取中…' : '重新读取'}
          </button>
        </div>
        {error ? (
          <InlineAlert
            variant="warning"
            title="已连接账户暂时不可用"
            message={error}
            className="mt-4"
          />
        ) : (
          <EmptyState
            title={loading ? '正在读取权威账户快照' : '尚未取得权威账户快照'}
            description="此视图只接受 Athena runtime 的 authoritative、read-only、simulation-only PortfolioSnapshot。"
            className="mt-4"
          />
        )}
      </Card>
    );
  }

  const degraded = snapshot.reconciliationStatus !== 'RECONCILED'
    || snapshot.dataQuality === 'LOW'
    || snapshot.dataQuality === 'UNKNOWN'
    || snapshot.limitations.length > 0;

  const facts = [
    ['账户权益', snapshot.equity],
    ['现金合计', snapshot.cash],
    ['可用现金', snapshot.availableCash],
    ['冻结现金', snapshot.reservedCash],
    ['已实现盈亏', snapshot.realizedPnl],
    ['未实现盈亏', snapshot.unrealizedPnl],
  ] as const;

  return (
    <div className="space-y-4" data-testid="connected-account-view">
      <Card padding="md" className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">Athena 已连接账户</h2>
              <Badge variant="info">已连接</Badge>
              <Badge variant="success">模拟账户</Badge>
              <Badge variant="default">只读</Badge>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary">
              <span>Broker · {snapshot.broker}</span>
              <span>账户模式 · 模拟</span>
              <span>Currency · {snapshot.currency}</span>
              <span>Snapshot · {formatDateTime(snapshot.asOf)}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(snapshot.reconciliationStatus)}>
              {reconciliationLabels[snapshot.reconciliationStatus]}
            </Badge>
            <Badge variant={statusVariant(snapshot.dataQuality)}>
              数据质量 · {dataQualityLabels[snapshot.dataQuality]}
            </Badge>
            <button type="button" className="btn-secondary text-sm" onClick={onRefresh} disabled={loading}>
              {loading ? '读取中…' : '刷新事实'}
            </button>
          </div>
        </div>
        {degraded ? (
          <InlineAlert
            variant="warning"
            title="权威快照存在限制"
            message={[
              `核对状态：${reconciliationLabels[snapshot.reconciliationStatus]}`,
              `数据质量：${dataQualityLabels[snapshot.dataQuality]}`,
              ...snapshot.limitations,
            ].join('；')}
            className="mt-4"
          />
        ) : null}
      </Card>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {facts.map(([label, value]) => (
          <Card key={label} variant="gradient" padding="md">
            <p className="text-xs text-secondary">{label}</p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {formatCanonicalMoney(value, snapshot.currency)}
            </p>
          </Card>
        ))}
      </section>

      <Card padding="md">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">权威持仓</h3>
            <p className="mt-1 text-xs text-secondary">按市场与股票代码精确区分；不与手工账户合并。</p>
          </div>
          <span className="text-xs text-secondary">{snapshot.positions.length} 项</span>
        </div>
        {snapshot.positions.length === 0 ? (
          <EmptyState title="暂无权威持仓" description="该结果来自 Athena 当前 observed runtime state。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[920px] w-full text-sm">
              <thead className="border-b border-white/10 text-xs text-secondary">
                <tr>
                  <th className="py-2 pr-3 text-left">市场</th>
                  <th className="py-2 pr-3 text-left">代码</th>
                  <th className="py-2 pr-3 text-right">数量 / 可用</th>
                  <th className="py-2 pr-3 text-right">平均成本</th>
                  <th className="py-2 pr-3 text-right">最新价</th>
                  <th className="py-2 pr-3 text-right">市值</th>
                  <th className="py-2 text-right">未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.positions.map((position) => (
                  <tr key={`${position.market}:${position.symbol}`} className="border-b border-white/5">
                    <td className="py-3 pr-3"><Badge variant="default">{position.market}</Badge></td>
                    <td className="py-3 pr-3 font-mono text-foreground">{position.symbol}</td>
                    <td className="py-3 pr-3 text-right">{position.quantity} / {position.availableQuantity}</td>
                    <td className="py-3 pr-3 text-right">{formatCanonicalMoney(position.avgCost, snapshot.currency)}</td>
                    <td className="py-3 pr-3 text-right">
                      <div>{formatCanonicalMoney(position.lastPrice, snapshot.currency)}</div>
                      <div className="text-[11px] text-secondary">{position.priceSource} · {formatDateTime(position.priceAsOf)}</div>
                    </td>
                    <td className="py-3 pr-3 text-right">{formatCanonicalMoney(position.marketValue, snapshot.currency)}</td>
                    <td className={`py-3 text-right ${Number(position.unrealizedPnl) >= 0 ? 'text-success' : 'text-danger'}`}>
                      {formatCanonicalMoney(position.unrealizedPnl, snapshot.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card padding="md">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">活动订单事实</h3>
            <p className="mt-1 text-xs text-secondary">仅观察，不提供撤单、重试、对账或任何执行控制。</p>
          </div>
          <Badge variant="default">只读 · {snapshot.activeOrders.length}</Badge>
        </div>
        {snapshot.activeOrders.length === 0 ? (
          <EmptyState title="暂无活动订单" description="此处不推断订单，也不触发 reconciliation。" />
        ) : (
          <div className="space-y-2">
            {snapshot.activeOrders.map((order) => (
              <div key={order.brokerOrderId} className="grid gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-3 text-xs md:grid-cols-6">
                <div><span className="text-secondary">代码</span><div className="mt-1 font-mono text-foreground">{order.symbol}</div></div>
                <div><span className="text-secondary">方向</span><div className="mt-1 text-foreground">{order.side === 'BUY' ? '买入' : '卖出'}</div></div>
                <div><span className="text-secondary">数量</span><div className="mt-1 text-foreground">{order.quantity}</div></div>
                <div><span className="text-secondary">成交 / 剩余</span><div className="mt-1 text-foreground">{order.filledQuantity} / {order.remainingQuantity}</div></div>
                <div><span className="text-secondary">状态</span><div className="mt-1"><Badge variant={order.state === 'UNKNOWN' ? 'danger' : 'warning'}>{orderStateLabels[order.state]}</Badge></div></div>
                <div><span className="text-secondary">冻结现金</span><div className="mt-1 text-foreground">{formatCanonicalMoney(order.reservedCash, snapshot.currency)}</div></div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <details className="rounded-xl border border-white/10 bg-white/[0.02] p-4 text-xs text-secondary">
        <summary className="cursor-pointer font-medium text-foreground">快照 lineage 与技术细节</summary>
        <dl className="mt-3 grid gap-2 break-all md:grid-cols-2">
          <div><dt>snapshot_id</dt><dd className="font-mono text-foreground">{snapshot.snapshotId}</dd></div>
          <div><dt>revision / supersedes</dt><dd className="font-mono text-foreground">{snapshot.revision} / {snapshot.supersedesId || '—'}</dd></div>
          <div><dt>producer</dt><dd className="font-mono text-foreground">{snapshot.producer}</dd></div>
          <div><dt>created_at</dt><dd className="font-mono text-foreground">{snapshot.createdAt}</dd></div>
          <div className="md:col-span-2"><dt>content_hash</dt><dd className="font-mono text-foreground">{snapshot.contentHash}</dd></div>
        </dl>
      </details>
    </div>
  );
};

export default ConnectedPortfolioAccountView;
