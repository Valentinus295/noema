import { useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, AreaChart, Area, Cell,
} from 'recharts';
import { useDashboard } from '@/contexts/DashboardContext';
import {
  formatCurrency,
  formatPips,
  formatPercent,
  formatRatio,
  pnlColor,
  directionBadge,
  computeDuration,
  formatTimestamp,
} from '@/utils/format';
import type { Trade, TradeStatus, WinRateBySymbol, WinRateBySession, WinRateByDayOfWeek, WinRateByHour } from '@/types';

type SortField = 'symbol' | 'direction' | 'entryPrice' | 'exitPrice' | 'pnl' | 'openedAt' | 'closedAt';
type SortDir = 'asc' | 'desc';

function TradeTable({
  trades,
  filter,
}: {
  trades: Trade[];
  filter: { symbol: string; direction: string; status: TradeStatus | '' };
}) {
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: 'openedAt',
    dir: 'desc',
  });

  const filtered = useMemo(() => {
    let result = [...trades];
    if (filter.symbol) result = result.filter((t) => t.symbol === filter.symbol);
    if (filter.direction) result = result.filter((t) => t.direction === filter.direction);
    if (filter.status) result = result.filter((t) => t.status === filter.status);
    result.sort((a, b) => {
      const aVal = a[sort.field];
      const bVal = b[sort.field];
      if (aVal === null) return 1;
      if (bVal === null) return -1;
      if (aVal < bVal) return sort.dir === 'asc' ? -1 : 1;
      if (aVal > bVal) return sort.dir === 'asc' ? 1 : -1;
      return 0;
    });
    return result;
  }, [trades, filter, sort]);

  const toggleSort = (field: SortField) => {
    setSort((prev) => ({
      field,
      dir: prev.field === field ? (prev.dir === 'asc' ? 'desc' : 'asc') : 'desc',
    }));
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sort.field !== field) return <span className="text-terminal-muted ml-1">⇅</span>;
    return <span className="text-blue-400 ml-1">{sort.dir === 'asc' ? '↑' : '↓'}</span>;
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-terminal-muted border-b border-terminal-border">
            {([
              ['symbol', 'Symbol'],
              ['direction', 'Dir'],
              ['entryPrice', 'Entry'],
              ['exitPrice', 'Exit'],
              ['pnl', 'P&L'],
              ['openedAt', 'Opened'],
              ['closedAt', 'Closed'],
              ['durationSeconds', 'Duration'],
            ] as [SortField, string][]).map(([field, label]) => (
              <th
                key={field}
                className="text-left py-2 px-2 font-medium cursor-pointer hover:text-terminal-text select-none"
                onClick={() => toggleSort(field)}
              >
                {label}
                <SortIcon field={field} />
              </th>
            ))}
            <th className="text-left py-2 px-2 font-medium">R:R</th>
            <th className="text-left py-2 px-2 font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((trade) => (
            <tr
              key={trade.id}
              className={`border-b border-terminal-border/50 hover:bg-terminal-border/20 transition-colors ${
                trade.pnl > 0 ? 'bg-trade-profit/5' : trade.pnl < 0 ? 'bg-trade-loss/5' : ''
              }`}
            >
              <td className="py-2 px-2 font-mono font-medium text-terminal-bright">{trade.symbol}</td>
              <td className="py-2 px-2">
                <span className={`badge ${directionBadge(trade.direction as string)}`}>
                  {trade.direction === 'BUY' ? 'LONG' : 'SHORT'}
                </span>
              </td>
              <td className="py-2 px-2 text-right font-mono">{trade.entryPrice.toFixed(5)}</td>
              <td className="py-2 px-2 text-right font-mono">
                {trade.exitPrice !== null ? trade.exitPrice.toFixed(5) : '—'}
              </td>
              <td className={`py-2 px-2 text-right font-mono font-medium ${pnlColor(trade.pnl)}`}>
                {formatCurrency(trade.pnl)}
              </td>
              <td className="py-2 px-2 font-mono text-terminal-muted">
                {formatTimestamp(trade.openedAt)}
              </td>
              <td className="py-2 px-2 font-mono text-terminal-muted">
                {formatTimestamp(trade.closedAt)}
              </td>
              <td className="py-2 px-2 font-mono text-terminal-muted">
                {trade.durationSeconds !== null
                  ? `${Math.floor(trade.durationSeconds / 60)}m`
                  : '—'}
              </td>
              <td className="py-2 px-2 font-mono text-terminal-muted">
                {formatRatio(trade.riskReward)}
              </td>
              <td className="py-2 px-2 font-mono text-terminal-muted max-w-[120px] truncate">
                {trade.closeReason || (trade.status === 'open' ? '—' : '—')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && (
        <div className="text-sm text-terminal-muted text-center py-12">
          No trades match the current filters
        </div>
      )}
    </div>
  );
}

function PnLDistribution({ data }: { data: import('@/types').PnLBin[] }) {
  if (data.length === 0) return null;
  return (
    <div className="card">
      <div className="card-header">P&L Distribution</div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="range" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip
            contentStyle={{ backgroundColor: '#14191f', border: '1px solid #1e2a36', borderRadius: 6 }}
            formatter={(value: number) => [value, 'Trades']}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {data.map((entry, idx) => {
              const isPositive = entry.range.startsWith('+') || entry.range.startsWith('$+');
              return (
                <Cell
                  key={idx}
                  fill={isPositive ? '#26a69a' : '#ef5350'}
                  fillOpacity={0.7}
                />
              );
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function WinRateChart({
  data,
  title,
  dataKey,
  nameKey,
  isHorizontal = false,
}: {
  data: Record<string, unknown>[];
  title: string;
  dataKey: string;
  nameKey: string;
  isHorizontal?: boolean;
}) {
  if (data.length === 0) return null;

  return (
    <div className="card">
      <div className="card-header">{title}</div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout={isHorizontal ? 'vertical' : 'horizontal'}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            type={isHorizontal ? 'number' : 'category'}
            dataKey={isHorizontal ? undefined : nameKey}
            tick={{ fontSize: 10 }}
            domain={isHorizontal ? [0, 1] : undefined}
            tickFormatter={isHorizontal ? (v: number) => `${(v * 100).toFixed(0)}%` : undefined}
          />
          <YAxis
            type={isHorizontal ? 'category' : 'number'}
            dataKey={isHorizontal ? nameKey : undefined}
            tick={{ fontSize: 10 }}
            domain={isHorizontal ? undefined : [0, 1]}
            tickFormatter={isHorizontal ? undefined : (v: number) => `${(v * 100).toFixed(0)}%`}
            width={isHorizontal ? 60 : 30}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#14191f', border: '1px solid #1e2a36', borderRadius: 6 }}
            formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, 'Win Rate']}
          />
          <Bar dataKey={dataKey} fill="#26a69a" fillOpacity={0.7} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function DrawdownChart({ data }: { data: import('@/types').EquityPoint[] }) {
  if (data.length === 0) return null;
  return (
    <div className="card">
      <div className="card-header">Drawdown</div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={(t: string) => {
              const d = new Date(t);
              return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
            }}
            tick={{ fontSize: 10 }}
          />
          <YAxis
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fontSize: 10 }}
            domain={['dataMin', 0]}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#14191f', border: '1px solid #1e2a36', borderRadius: 6 }}
            formatter={(value: number) => [`${(value * 100).toFixed(2)}%`, 'Drawdown']}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#ef5350"
            strokeWidth={2}
            fill="#ef5350"
            fillOpacity={0.1}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Trades() {
  const { state } = useDashboard();
  const { trades, metrics } = state;

  const [symbolFilter, setSymbolFilter] = useState('');
  const [directionFilter, setDirectionFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<TradeStatus | ''>('');

  const symbols = useMemo(() => {
    const s = new Set(trades.map((t) => t.symbol));
    return Array.from(s).sort();
  }, [trades]);

  const summary = useMemo(() => {
    const closed = trades.filter((t) => t.status === 'closed');
    const wins = closed.filter((t) => t.pnl > 0).length;
    return {
      total: closed.length,
      wins,
      losses: closed.length - wins,
      winRate: closed.length > 0 ? wins / closed.length : 0,
      totalPnl: closed.reduce((s, t) => s + t.pnl, 0),
    };
  }, [trades]);

  return (
    <div className="p-4 space-y-4 animate-fade-in">
      <h2 className="text-lg font-semibold text-terminal-bright">Trade History</h2>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="card">
          <div className="card-header">Closed Trades</div>
          <div className="stat-value text-terminal-bright">{summary.total}</div>
        </div>
        <div className="card">
          <div className="card-header">Win Rate</div>
          <div className={`stat-value ${summary.winRate >= 0.5 ? 'text-trade-profit' : 'text-trade-loss'}`}>
            {formatPercent(summary.winRate * 100, 0)}
          </div>
        </div>
        <div className="card">
          <div className="card-header">Wins</div>
          <div className="stat-value text-trade-profit">{summary.wins}</div>
        </div>
        <div className="card">
          <div className="card-header">Losses</div>
          <div className="stat-value text-trade-loss">{summary.losses}</div>
        </div>
        <div className="card">
          <div className="card-header">Total P&L</div>
          <div className={`stat-value ${pnlColor(summary.totalPnl)}`}>
            {formatCurrency(summary.totalPnl)}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="input-field text-xs"
        >
          <option value="">All Symbols</option>
          {symbols.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={directionFilter}
          onChange={(e) => setDirectionFilter(e.target.value)}
          className="input-field text-xs"
        >
          <option value="">All Directions</option>
          <option value="BUY">Long</option>
          <option value="SELL">Short</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as TradeStatus | '')}
          className="input-field text-xs"
        >
          <option value="">All Status</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <div className="text-2xs text-terminal-muted font-mono ml-auto">
          {trades.length} trades
        </div>
      </div>

      {/* Trade table */}
      <div className="card p-2">
        <TradeTable
          trades={trades}
          filter={{ symbol: symbolFilter, direction: directionFilter, status: statusFilter }}
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PnLDistribution data={metrics?.pnlDistribution ?? []} />
        <DrawdownChart data={metrics?.drawdownHistory ?? []} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <WinRateChart
          data={(metrics?.winRateBySymbol ?? []) as unknown as Record<string, unknown>[]}
          title="Win Rate by Symbol"
          dataKey="winRate"
          nameKey="symbol"
        />
        <WinRateChart
          data={(metrics?.winRateBySession ?? []) as unknown as Record<string, unknown>[]}
          title="Win Rate by Session"
          dataKey="winRate"
          nameKey="session"
        />
        <WinRateChart
          data={(metrics?.winRateByDayOfWeek ?? []) as unknown as Record<string, unknown>[]}
          title="Win Rate by Day"
          dataKey="winRate"
          nameKey="day"
        />
        <WinRateChart
          data={(metrics?.winRateByHour ?? []) as unknown as Record<string, unknown>[]}
          title="Win Rate by Hour"
          dataKey="winRate"
          nameKey="hour"
        />
      </div>
    </div>
  );
}
