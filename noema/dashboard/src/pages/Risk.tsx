import { useMemo } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import { formatCurrency, formatPercent } from '@/utils/format';
import type { KillSwitch } from '@/types';

function Gauge({
  value,
  max,
  label,
  format = 'percent',
  warning = 70,
  critical = 90,
}: {
  value: number;
  max: number;
  label: string;
  format?: 'percent' | 'currency';
  warning?: number;
  critical?: number;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color =
    pct >= critical ? '#ff1744' : pct >= warning ? '#ffd600' : '#00e676';

  const formattedValue = format === 'currency' ? formatCurrency(value) : formatPercent(value, 1);
  const formattedMax = format === 'currency' ? formatCurrency(max) : formatPercent(max, 1);

  return (
    <div className="card">
      <div className="card-header">{label}</div>
      <div className="flex items-end justify-between mb-2">
        <span className="font-mono text-xl font-semibold" style={{ color }}>
          {formattedValue}
        </span>
        <span className="text-xs text-terminal-muted font-mono">/ {formattedMax}</span>
      </div>
      <div className="w-full h-2 bg-terminal-border rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <div className="flex justify-between mt-1 text-2xs text-terminal-muted font-mono">
        <span>Safe</span>
        <span>Warning {warning}%</span>
        <span>Critical {critical}%</span>
      </div>
    </div>
  );
}

function KillSwitchPanel({ switches }: { switches: KillSwitch[] }) {
  return (
    <div className="card">
      <div className="card-header">
        Kill Switches ({switches.filter((s) => s.active).length} tripped / {switches.length})
      </div>
      <div className="space-y-1.5">
        {switches.map((ks) => (
          <div
            key={ks.id}
            className={`flex items-center justify-between px-3 py-2 rounded text-xs ${
              ks.active
                ? 'bg-red-500/10 border border-red-500/25'
                : 'bg-terminal-border/20 border border-transparent'
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`inline-block w-2 h-2 rounded-full shrink-0 ${
                  ks.active ? 'bg-status-red' : 'bg-status-green'
                }`}
              />
              <div className="min-w-0">
                <div className="font-medium text-terminal-bright truncate">{ks.name}</div>
                <div className="text-2xs text-terminal-muted truncate">{ks.description}</div>
              </div>
            </div>
            <div className="text-right ml-3 shrink-0">
              <div className={`font-mono font-medium ${ks.active ? 'text-trade-loss' : 'text-trade-profit'}`}>
                {ks.value}
              </div>
              <div className="text-2xs text-terminal-muted font-mono">
                threshold: {ks.threshold}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CorrelationHeatmap({ data }: { data: import('@/types').CorrelationMatrix }) {
  if (!data || data.symbols.length === 0) {
    return (
      <div className="card">
        <div className="card-header">Correlation Matrix</div>
        <div className="text-sm text-terminal-muted text-center py-8">
          No open positions to correlate
        </div>
      </div>
    );
  }

  const getColor = (value: number) => {
    if (value >= 0.8) return 'bg-red-500/80';
    if (value >= 0.5) return 'bg-amber-500/60';
    if (value >= 0) return 'bg-slate-500/30';
    if (value >= -0.5) return 'bg-blue-500/30';
    return 'bg-blue-500/60';
  };

  return (
    <div className="card">
      <div className="card-header">Correlation Matrix</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr>
              <th className="p-1"></th>
              {data.symbols.map((s) => (
                <th key={s} className="p-1 text-terminal-muted font-medium">{s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.symbols.map((s, i) => (
              <tr key={s}>
                <td className="p-1 text-terminal-muted font-medium">{s}</td>
                {data.values[i]?.map((v, j) => (
                  <td key={j} className="p-1">
                    <div
                      className={`w-full h-8 rounded flex items-center justify-center ${getColor(v)} ${
                        i === j ? 'ring-1 ring-terminal-muted' : ''
                      }`}
                      title={`${s} × ${data.symbols[j]}: ${v.toFixed(2)}`}
                    >
                      <span className="text-white font-bold">{v.toFixed(2)}</span>
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OpenPositionsRisk({ positions }: { positions: import('@/types').Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="card">
        <div className="card-header">Open Position Details</div>
        <div className="text-sm text-terminal-muted text-center py-8">No open positions</div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">Open Position Details</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-terminal-muted border-b border-terminal-border">
              <th className="text-left py-2 px-2">Symbol</th>
              <th className="text-left py-2 px-2">Dir</th>
              <th className="text-right py-2 px-2">Volume</th>
              <th className="text-right py-2 px-2">Entry</th>
              <th className="text-right py-2 px-2">Current</th>
              <th className="text-right py-2 px-2">SL</th>
              <th className="text-right py-2 px-2">P&L</th>
              <th className="text-right py-2 px-2">Pips</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <tr key={pos.ticket} className="border-b border-terminal-border/50">
                <td className="py-2 px-2 font-mono font-medium text-terminal-bright">{pos.symbol}</td>
                <td className="py-2 px-2">
                  <span className={`badge ${pos.direction === 'buy' ? 'badge-green' : 'badge-red'}`}>
                    {pos.direction.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 px-2 text-right font-mono">{pos.volume.toFixed(2)}</td>
                <td className="py-2 px-2 text-right font-mono">{pos.openPrice.toFixed(5)}</td>
                <td className="py-2 px-2 text-right font-mono">{pos.currentPrice.toFixed(5)}</td>
                <td className="py-2 px-2 text-right font-mono text-trade-loss">{pos.stopLoss.toFixed(5)}</td>
                <td className={`py-2 px-2 text-right font-mono font-medium ${pos.pnl >= 0 ? 'text-trade-profit' : 'text-trade-loss'}`}>
                  {formatCurrency(pos.pnl)}
                </td>
                <td className={`py-2 px-2 text-right font-mono ${pos.pnlPips >= 0 ? 'text-trade-profit' : 'text-trade-loss'}`}>
                  {pos.pnlPips >= 0 ? '+' : ''}{pos.pnlPips.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Risk() {
  const { state } = useDashboard();
  const { riskMetrics, systemHealth } = state;

  const killSwitches = riskMetrics?.killSwitches ?? [];

  const trippedCount = killSwitches.filter((s) => s.active).length;

  return (
    <div className="p-4 space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-terminal-bright">Risk Monitor</h2>
        {trippedCount > 0 && (
          <span className="text-sm font-mono text-trade-loss bg-red-500/10 px-3 py-1 rounded border border-red-500/25">
            ⚠ {trippedCount} Kill Switches Tripped
          </span>
        )}
      </div>

      {/* Top gauges */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Gauge
          label="Current Exposure"
          value={riskMetrics?.currentExposurePct ?? 0}
          max={riskMetrics?.maxExposurePct ?? 100}
        />
        <Gauge
          label="Daily Loss"
          value={Math.abs(riskMetrics?.dailyLossPct ?? 0)}
          max={riskMetrics?.dailyLossLimitPct ?? 5}
          warning={50}
          critical={80}
        />
        <div className="card">
          <div className="card-header">Consecutive Losses</div>
          <div className={`stat-value ${(riskMetrics?.consecutiveLosses ?? 0) >= 5 ? 'text-trade-loss' : (riskMetrics?.consecutiveLosses ?? 0) >= 3 ? 'text-amber-400' : 'text-trade-profit'}`}>
            {riskMetrics?.consecutiveLosses ?? 0}
          </div>
          <div className="stat-label">
            Max allowed: {riskMetrics?.maxConsecutiveLosses ?? '—'}
          </div>
        </div>
        <div className="card">
          <div className="card-header">Margin Level</div>
          <div className={`stat-value ${(riskMetrics?.marginLevel ?? 0) > (riskMetrics?.marginLevelWarning ?? 200) ? 'text-trade-profit' : 'text-trade-loss'}`}>
            {riskMetrics?.marginLevel?.toFixed(0) ?? '—'}%
          </div>
          <div className="stat-label">
            Warning: {riskMetrics?.marginLevelWarning?.toFixed(0) ?? '200'}% · Free: {riskMetrics?.freeMargin ? formatCurrency(riskMetrics.freeMargin) : '—'}
          </div>
        </div>
      </div>

      {/* Kill Switches + Correlation Matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <KillSwitchPanel switches={killSwitches} />
        <CorrelationHeatmap data={riskMetrics?.correlationMatrix ?? { symbols: [], values: [] }} />
      </div>

      {/* Open positions table */}
      <OpenPositionsRisk positions={riskMetrics?.openPositions ?? state.positions} />
    </div>
  );
}
