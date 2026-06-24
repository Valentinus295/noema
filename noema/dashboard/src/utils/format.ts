import { format, formatDistanceToNow, differenceInSeconds, differenceInMinutes, differenceInHours } from 'date-fns';

/**
 * Format a number as currency with appropriate decimal places.
 */
export function formatCurrency(value: number, compact = false): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : value >= 0 ? '' : '';

  if (compact && abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  }
  if (compact && abs >= 1_000) {
    return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  }

  const decimals = abs < 1 ? 4 : abs < 10 ? 2 : abs < 100 ? 2 : 0;
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

/**
 * Format a percentage value.
 */
export function formatPercent(value: number, decimals = 1): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

/**
 * Format a ratio (RR ratio).
 */
export function formatRatio(value: number | null): string {
  if (value === null || value === undefined) return '—';
  return `1:${value.toFixed(2)}`;
}

/**
 * Format pips.
 */
export function formatPips(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}`;
}

/**
 * Format a duration from seconds into a human-readable string.
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

/**
 * Format a timestamp for display.
 */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  return format(new Date(iso), 'MMM dd HH:mm:ss');
}

/**
 * Format a relative time (e.g. "2 minutes ago").
 */
export function formatRelativeTime(iso: string | null): string {
  if (!iso) return '—';
  return formatDistanceToNow(new Date(iso), { addSuffix: true });
}

/**
 * Format elapsed time from seconds.
 */
export function formatElapsed(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

/**
 * Compute a human-readable duration between two ISO timestamps.
 */
export function computeDuration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const s = new Date(start);
  const e = new Date(end);
  const totalSeconds = differenceInSeconds(e, s);
  return formatDuration(totalSeconds);
}

/**
 * Color class helpers.
 */
export function pnlColor(value: number): string {
  if (value > 0) return 'text-trade-profit';
  if (value < 0) return 'text-trade-loss';
  return 'text-terminal-muted';
}

export function pnlBgColor(value: number): string {
  if (value > 0) return 'bg-trade-profit/10';
  if (value < 0) return 'bg-trade-loss/10';
  return 'bg-terminal-border/50';
}

export function directionColor(dir: string): string {
  if (dir === 'BUY' || dir === 'buy') return 'text-trade-buy';
  if (dir === 'SELL' || dir === 'sell') return 'text-trade-sell';
  return 'text-terminal-muted';
}

export function directionBadge(dir: string): string {
  if (dir === 'BUY' || dir === 'buy') return 'badge-green';
  if (dir === 'SELL' || dir === 'sell') return 'badge-red';
  return 'badge-neutral';
}

/**
 * Format a number with K/M suffix.
 */
export function formatCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(1);
}
