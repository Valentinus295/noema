import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart,
} from 'recharts';
import { useDashboard } from '@/contexts/DashboardContext';
import { formatCurrency, formatPercent, formatPips, pnlColor, directionColor, directionBadge, formatDuration, formatRelativeTime } from '@/utils/format';
import { TradingChart } from '@/components/TradingChart';
import type { EquityPoint } from '@/types';

function PnLCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: number;
  sub?: string;
}) {
  return (
    <div className="card">
      <div className="card-header">{label}</div>
      <div className={`stat-value ${pnlColor(value)}`}>
        {formatCurrency(value)}
      </div>
      {sub && <div className="stat-label">{sub}</div>}
    </div>
  );
}

function MetricCard({
  label,
  value,
  format = 'number',
}: {
  label: string;
  value: string | number;
  format?: 'number' | 'percent' | 'currency';
}) {
  const formatted =
    format === 'percent'
      ? formatPercent(Number(value))
      : format === 'currency'
      ? formatCurrency(Number(value))
      : String(value);
  return (
    <div className="card">
      <div className="card-header">{label}</div>
      <div className="stat-value text-terminal-bright">{formatted}</div>
    </div>
  );
}

function EquityCurveChart({ data }: { data: EquityPoint[] }) {
  if (data.length === 0) {
    return <div className="text-sm text-terminal-muted text-center py-12">No equity data available</div>;
  }

  const values = data.map((d) => d.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = (max - min) * 0.1 || max * 0.05;

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#26a69a" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#26a69a" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="timestamp"
          tickFormatter={(t: string) => {
            const d = new Date(t);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          }}
          tick={{ fontSize: 10 }}
        />
        <YAxis
          domain={[min - padding, max + padding]}
          tickFormatter={(v: number) => `$${v.toFixed(0)}`}
          tick={{ fontSize: 10 }}
          width={60}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#14191f',
            border: '1px solid #1e2a36',
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(label: string) => new Date(label).toLocaleString()}
          formatter={(value: number) => [`$${value.toFixed(2)}`, 'Equity']}
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="#26a69a"
          strokeWidth={2}
          fill="url(#equityGrad)"
          dot={false}
          animationDuration={500}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function WinRateGauge({ value, label }: { value: number; label: string }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  const color = pct >= 55 ? 'text-trade-profit' : pct >= 45 ? 'text-trade-neutral' : 'text-trade-loss';

  return (
    <div className="card flex flex-col items-center">
      <div className="card-header">{label}</div>
      <div className="relative w-20 h-20">
        <svg viewBox="0 0 100 100" className="transform -rotate-90">
          <circle cx="50" cy="50" r="42" fill="none" stroke="#1e2a36" strokeWidth="8" />
          <circle
            cx="50" cy="50" r="42" fill="none"
            stroke={pct >= 55 ? '#00c853' : pct >= 45 ? '#78909c' : '#ff1744'}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${pct * 2.64} 264`}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-lg font-mono font-bold ${color}`}>
            {pct.toFixed(0)}%
          </span>
        </div>
      </div>
    </div>
  );
}

export function Dashboard() {
  const { state } = useDashboard();
  const { metrics, positions, systemHealth } = state;

  const openPositions = positions.filter((p) => p.volume > 0);

  return (
    <div className="p-4 space-y-3 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-terminal-bright">
          Trading Dashboard
        </h2>
        <div className="text-xs text-terminal-muted font-mono">
          {systemHealth?.pipelineActive && (
            <span className="text-status-green">● Pipeline Active</span>
          )}
          {!systemHealth?.pipelineActive && (
            <span className="text-terminal-muted">● Pipeline Idle</span>
          )}
        </div>
      </div>

      {/* P&L Cards Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <PnLCard
          label="Daily P&L"
          value={metrics?.dailyPnl ?? 0}
          sub={metrics ? `${metrics.winRate > 0 ? 'WR ' + formatPercent(metrics.winRate * 100, 0) : ''}` : undefined}
        />
        <PnLCard label="Weekly P&L" value={metrics?.weeklyPnl ?? 0} />
        <PnLCard label="Monthly P&L" value={metrics?.monthlyPnl ?? 0} />
        <div className="card">
          <div className="card-header">Balance / Equity</div>
          <div className="stat-value text-terminal-bright">
            {metrics ? formatCurrency(metrics.equity) : '—'}
          </div>
          <div className="stat-label">
            Balance: {metrics ? formatCurrency(metrics.balance) : '—'}
          </div>
        </div>
      </div>

      {/* TradingView Chart — Hero Section */}
      <div className="card p-0 overflow-hidden">
        <TradingChart className="h-[520px]" />
      </div>

      {/* Bottom row: Equity Curve + Positions + Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Equity Curve */}
        <div className="card lg:col-span-2">
          <div className="card-header">Equity Curve</div>
          <EquityCurveChart data={metrics?.equityCurve ?? []} />
        </div>

        {/* Win Rate Gauge + Quick Stats */}
        <div className="space-y-3">
          <WinRateGauge value={metrics?.winRate ?? 0} label="Overall Win Rate" />
          <div className="card space-y-2">
            <div className="card-header">Quick Stats</div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Total Trades</span>
              <span className="font-mono text-terminal-bright">{metrics?.totalTrades ?? 0}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Profit Factor</span>
              <span className="font-mono text-terminal-bright">{metrics?.profitFactor?.toFixed(2) ?? '—'}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Sharpe Ratio</span>
              <span className="font-mono text-terminal-bright">{metrics?.sharpeRatio?.toFixed(2) ?? '—'}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Max Drawdown</span>
              <span className="font-mono text-trade-loss">{formatPercent(metrics?.maxDrawdown ?? 0)}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Avg R:R</span>
              <span className="font-mono text-terminal-bright">1:{metrics?.avgRR?.toFixed(2) ?? '—'}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Best Trade</span>
              <span className="font-mono text-trade-profit">{formatCurrency(metrics?.bestTrade ?? 0)}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-terminal-muted">Worst Trade</span>
              <span className="font-mono text-trade-loss">{formatCurrency(metrics?.worstTrade ?? 0)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Open Positions Table */}
      <div className="card">
        <div className="card-header flex items-center justify-between">
          <span>Open Positions ({openPositions.length})</span>
          {openPositions.length > 0 && (
            <span className="text-status-green text-xs font-normal">● Live</span>
          )}
        </div>
        {openPositions.length === 0 ? (
          <div className="text-sm text-terminal-muted text-center py-6">
            No open positions
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-terminal-muted border-b border-terminal-border">
                  <th className="text-left py-2 px-2 font-medium">Symbol</th>
                  <th className="text-left py-2 px-2 font-medium">Dir</th>
                  <th className="text-right py-2 px-2 font-medium">Entry</th>
                  <th className="text-right py-2 px-2 font-medium">Current</th>
                  <th className="text-right py-2 px-2 font-medium">SL</th>
                  <th className="text-right py-2 px-2 font-medium">TP</th>
                  <th className="text-right py-2 px-2 font-medium">P&L</th>
                  <th className="text-right py-2 px-2 font-medium">Pips</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((pos) => (
                  <tr key={pos.ticket} className="border-b border-terminal-border/50 hover:bg-terminal-border/20 transition-colors">
                    <td className="py-2 px-2 font-mono font-medium text-terminal-bright">
                      {pos.symbol}
                    </td>
                    <td className="py-2 px-2">
                      <span className={`badge ${directionBadge(pos.direction)}`}>
                        {pos.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right font-mono">{pos.openPrice.toFixed(5)}</td>
                    <td className={`py-2 px-2 text-right font-mono ${pos.currentPrice > pos.openPrice ? 'text-trade-buy' : 'text-trade-sell'}`}>
                      {pos.currentPrice.toFixed(5)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-trade-loss">{pos.stopLoss.toFixed(5)}</td>
                    <td className="py-2 px-2 text-right font-mono text-trade-profit">{pos.takeProfit.toFixed(5)}</td>
                    <td className={`py-2 px-2 text-right font-mono ${pnlColor(pos.pnl)}`}>
                      {formatCurrency(pos.pnl)}
                    </td>
                    <td className={`py-2 px-2 text-right font-mono ${pnlColor(pos.pnl)}`}>
                      {formatPips(pos.pnlPips)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
