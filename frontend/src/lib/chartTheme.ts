/**
 * Shared chart language. Every chart in the app reads from this palette so
 * Histórico, Próximos and the Dashboard speak the same visual dialect.
 */

export const CHART_COLORS = {
  primary: "#2563eb",
  primarySelected: "#1d4ed8",
  primarySoft: "#93c5fd",
  positive: "#10b981",
  negative: "#f43f5e",
  warning: "#f59e0b",
  neutral: "#94a3b8",
  muted: "#cbd5e1",
  grid: "#eef0f4",
  tick: "#64748b",
  valueLabel: "#334155",
} as const;

export const CHART_SERIES = [
  "#2563eb",
  "#7c3aed",
  "#0d9488",
  "#ea580c",
  "#db2777",
  "#0ea5e9",
] as const;

export const CHART_FONT = {
  family: "Inter, ui-sans-serif, system-ui, sans-serif",
  size: 11,
} as const;
