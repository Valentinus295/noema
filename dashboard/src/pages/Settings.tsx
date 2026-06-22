import { useState } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import type { SymbolConfig } from '@/types';

function Toggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      className={`toggle-switch ${enabled ? 'toggle-switch-on' : 'toggle-switch-off'}`}
      onClick={() => onChange(!enabled)}
      role="switch"
      aria-checked={enabled}
    >
      <span className={`toggle-knob ${enabled ? 'toggle-knob-on' : 'toggle-knob-off'}`} />
    </button>
  );
}

function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  unit,
  description,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  description?: string;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-terminal-border/50 last:border-b-0">
      <div className="min-w-0 mr-4">
        <div className="text-sm text-terminal-text">{label}</div>
        {description && <div className="text-2xs text-terminal-muted mt-0.5">{description}</div>}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          min={min}
          max={max}
          step={step ?? 0.01}
          className="input-field w-24 text-right font-mono"
        />
        {unit && <span className="text-xs text-terminal-muted font-mono w-8">{unit}</span>}
      </div>
    </div>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="card-header">{title}</div>
      <div>{children}</div>
    </div>
  );
}

export function Settings() {
  const { state, fetchApi } = useDashboard();
  const { settings } = state;

  const [localSettings, setLocalSettings] = useState(() => ({
    riskPctPerTrade: settings?.riskPctPerTrade ?? 0.25,
    maxConcurrentPositions: settings?.maxConcurrentPositions ?? 3,
    maxPerSymbol: settings?.maxPerSymbol ?? 1,
    dailyLossLimitPct: settings?.dailyLossLimitPct ?? 1.0,
    maxSpreadPips: settings?.maxSpreadPips ?? 3.0,
    minRR: settings?.minRR ?? 2.0,
    confluenceThreshold: settings?.confluenceThreshold ?? 0.70,
    llmReviewEnabled: settings?.llmReviewEnabled ?? false,
  }));

  const [symbols, setSymbols] = useState<SymbolConfig[]>(
    settings?.symbols ?? [
      { symbol: 'EURUSD', enabled: true, maxSpread: 1.5 },
      { symbol: 'GBPUSD', enabled: true, maxSpread: 2.0 },
      { symbol: 'USDJPY', enabled: true, maxSpread: 1.5 },
      { symbol: 'AUDUSD', enabled: true, maxSpread: 2.0 },
      { symbol: 'XAUUSD', enabled: true, maxSpread: 5.0 },
    ],
  );

  const [sessions, setSessions] = useState({
    sydney: settings?.sessions?.sydney ?? false,
    tokyo: settings?.sessions?.tokyo ?? false,
    london: settings?.sessions?.london ?? true,
    newYork: settings?.sessions?.newYork ?? true,
    londonNYOverlap: settings?.sessions?.londonNYOverlap ?? true,
  });

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const updateSymbol = (index: number, updates: Partial<SymbolConfig>) => {
    setSymbols((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], ...updates };
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetchApi('/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          risk: {
            risk_pct_per_trade: localSettings.riskPctPerTrade,
            max_concurrent_positions: localSettings.maxConcurrentPositions,
            max_per_symbol: localSettings.maxPerSymbol,
            daily_loss_limit_pct: localSettings.dailyLossLimitPct,
            max_spread_pips: localSettings.maxSpreadPips,
          },
          confluence: {
            threshold: localSettings.confluenceThreshold,
            llm_review_enabled: localSettings.llmReviewEnabled,
          },
          symbols,
          sessions,
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      console.error('Failed to save settings:', err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-terminal-bright">Settings</h2>
        <div className="flex items-center gap-3">
          {saved && (
            <span className="text-xs text-trade-profit font-mono">✓ Saved</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary text-xs"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Risk Parameters */}
        <SettingsSection title="Risk Parameters">
          <NumberInput
            label="Risk Per Trade"
            value={localSettings.riskPctPerTrade}
            onChange={(v) => setLocalSettings((s) => ({ ...s, riskPctPerTrade: v }))}
            min={0.05}
            max={5.0}
            step={0.05}
            unit="%"
            description="Percentage of balance risked per trade"
          />
          <NumberInput
            label="Max Daily Loss"
            value={localSettings.dailyLossLimitPct}
            onChange={(v) => setLocalSettings((s) => ({ ...s, dailyLossLimitPct: v }))}
            min={0.1}
            max={10.0}
            step={0.1}
            unit="%"
            description="Halt trading if daily loss exceeds this"
          />
          <NumberInput
            label="Max Concurrent Positions"
            value={localSettings.maxConcurrentPositions}
            onChange={(v) => setLocalSettings((s) => ({ ...s, maxConcurrentPositions: v }))}
            min={1}
            max={10}
            step={1}
            description="Maximum open positions at any time"
          />
          <NumberInput
            label="Max Per Symbol"
            value={localSettings.maxPerSymbol}
            onChange={(v) => setLocalSettings((s) => ({ ...s, maxPerSymbol: v }))}
            min={1}
            max={5}
            step={1}
            description="Maximum concurrent trades per symbol"
          />
          <NumberInput
            label="Max Spread (Pips)"
            value={localSettings.maxSpreadPips}
            onChange={(v) => setLocalSettings((s) => ({ ...s, maxSpreadPips: v }))}
            min={0.5}
            max={10.0}
            step={0.5}
            unit="pips"
            description="Reject trades if spread exceeds this"
          />
          <NumberInput
            label="Minimum R:R Ratio"
            value={localSettings.minRR}
            onChange={(v) => setLocalSettings((s) => ({ ...s, minRR: v }))}
            min={1.0}
            max={10.0}
            step={0.1}
            description="Minimum reward-to-risk ratio required"
          />
        </SettingsSection>

        {/* Confluence & LLM */}
        <SettingsSection title="Decision Parameters">
          <NumberInput
            label="Confluence Threshold"
            value={localSettings.confluenceThreshold}
            onChange={(v) => setLocalSettings((s) => ({ ...s, confluenceThreshold: v }))}
            min={0.4}
            max={0.95}
            step={0.01}
            description="Minimum confluence score to proceed"
          />
          <div className="flex items-center justify-between py-2.5">
            <div>
              <div className="text-sm text-terminal-text">LLM Review</div>
              <div className="text-2xs text-terminal-muted mt-0.5">
                Enable LLM-powered CIO review on borderline setups
              </div>
            </div>
            <Toggle
              enabled={localSettings.llmReviewEnabled}
              onChange={(v) => setLocalSettings((s) => ({ ...s, llmReviewEnabled: v }))}
            />
          </div>
        </SettingsSection>

        {/* Symbol Whitelist */}
        <SettingsSection title="Symbol Whitelist">
          <div className="space-y-1">
            {symbols.map((sym, idx) => (
              <div
                key={sym.symbol}
                className="flex items-center justify-between py-2 border-b border-terminal-border/50 last:border-b-0"
              >
                <div className="flex items-center gap-3">
                  <Toggle
                    enabled={sym.enabled}
                    onChange={(v) => updateSymbol(idx, { enabled: v })}
                  />
                  <span className={`text-sm font-mono font-medium ${sym.enabled ? 'text-terminal-bright' : 'text-terminal-muted'}`}>
                    {sym.symbol}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-2xs text-terminal-muted">Spread:</span>
                  <input
                    type="number"
                    value={sym.maxSpread}
                    onChange={(e) => updateSymbol(idx, { maxSpread: parseFloat(e.target.value) || 0 })}
                    min={0.5}
                    max={20}
                    step={0.5}
                    className="input-field w-20 text-right text-xs font-mono"
                  />
                  <span className="text-2xs text-terminal-muted">pips</span>
                </div>
              </div>
            ))}
          </div>
        </SettingsSection>

        {/* Session Configuration */}
        <SettingsSection title="Session Configuration">
          <div className="space-y-2">
            {([
              { key: 'london', label: 'London', time: '11:00–19:00 UTC+3' },
              { key: 'newYork', label: 'New York', time: '16:00–24:00 UTC+3' },
              { key: 'londonNYOverlap', label: 'London/NY Overlap', time: '16:00–19:00 UTC+3' },
              { key: 'tokyo', label: 'Tokyo', time: '02:00–11:00 UTC+3' },
              { key: 'sydney', label: 'Sydney', time: '00:00–08:00 UTC+3' },
            ] as const).map(({ key, label, time }) => (
              <div
                key={key}
                className="flex items-center justify-between py-2 border-b border-terminal-border/50 last:border-b-0"
              >
                <div className="flex items-center gap-3">
                  <Toggle
                    enabled={sessions[key]}
                    onChange={(v) => setSessions((s) => ({ ...s, [key]: v }))}
                  />
                  <div>
                    <div className="text-sm text-terminal-text">{label}</div>
                    <div className="text-2xs text-terminal-muted font-mono">{time}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </SettingsSection>

        {/* Broker Status */}
        <SettingsSection title="Broker Connection">
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-terminal-text">Status</span>
              <span className={`badge ${settings?.brokerConnected ? 'badge-green' : 'badge-red'}`}>
                {settings?.brokerConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Account</span>
              <span className="text-sm font-mono text-terminal-bright">
                {settings?.brokerAccount || '—'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Server</span>
              <span className="text-sm font-mono text-terminal-bright">
                {settings?.brokerServer || '—'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">SL Method</span>
              <span className="badge badge-neutral text-xs">{settings?.slMethod?.toUpperCase() || 'ATR'}</span>
            </div>
          </div>
        </SettingsSection>

        {/* System Info */}
        <SettingsSection title="System Info">
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-terminal-text">Version</span>
              <span className="text-sm font-mono text-terminal-bright">
                {state.systemHealth?.version || '—'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Uptime</span>
              <span className="text-sm font-mono text-terminal-bright">
                {state.systemHealth?.uptime
                  ? `${Math.floor(state.systemHealth.uptime / 3600)}h ${Math.floor((state.systemHealth.uptime % 3600) / 60)}m`
                  : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Pipeline Latency</span>
              <span className="text-sm font-mono text-terminal-bright">
                {state.systemHealth?.pipelineLatencyMs !== null
                  ? `${state.systemHealth?.pipelineLatencyMs?.toFixed(0)}ms`
                  : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Redis</span>
              <span className={`badge ${state.systemHealth?.redisConnected ? 'badge-green' : 'badge-red'}`}>
                {state.systemHealth?.redisConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">Database</span>
              <span className={`badge ${state.systemHealth?.dbConnected ? 'badge-green' : 'badge-red'}`}>
                {state.systemHealth?.dbConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">LLM (NIM)</span>
              <span
                className={`badge ${
                  state.systemHealth?.llmStatus === 'online'
                    ? 'badge-green'
                    : state.systemHealth?.llmStatus === 'degraded'
                    ? 'badge-yellow'
                    : 'badge-red'
                }`}
              >
                {state.systemHealth?.llmStatus?.toUpperCase() || 'UNKNOWN'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-t border-terminal-border/50">
              <span className="text-sm text-terminal-text">WebSocket</span>
              <span className={`badge ${state.wsConnected ? 'badge-green' : 'badge-red'}`}>
                {state.wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}
