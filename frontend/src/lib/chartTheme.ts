/**
 * Shared chart language. Every chart in the app reads from this palette so
 * Histórico, Próximos and the Dashboard speak the same visual dialect.
 */

export const CHART_COLORS = {
  primary: "#18778a",
  primarySelected: "#123e4b",
  primarySoft: "#9bc7d0",
  positive: "#159a73",
  negative: "#e46358",
  warning: "#d7942a",
  neutral: "#94a3b8",
  muted: "#cbd5e1",
  grid: "#edf2f4",
  tick: "#607582",
  valueLabel: "#304958",
  tooltip: "#123e4b",
} as const;

export const CHART_FONT = {
  family: "Inter, ui-sans-serif, system-ui, sans-serif",
  size: 11,
} as const;
