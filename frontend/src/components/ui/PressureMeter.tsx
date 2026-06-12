import { classNames } from "../../lib/classNames";
import { percent } from "../../lib/money";
import { ProgressBar } from "./ProgressBar";

interface PressureMeterProps {
  label: string;
  /** Share of the month this component consumes, in percent (can exceed 100). */
  value: number;
  detail?: string;
  className?: string;
}

/**
 * Pressure indicator: how much of the month a component (fatura, fixos,
 * variáveis) consumes. Color escalates with pressure so the user reads risk
 * at a glance.
 */
export function PressureMeter({ label, value, detail, className }: PressureMeterProps) {
  const tone = value > 95 ? "danger" : value > 70 ? "warning" : "positive";
  const toneText =
    tone === "danger" ? "text-danger-700" : tone === "warning" ? "text-warning-700" : "text-positive-700";
  return (
    <div className={classNames("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <p className="truncate text-xs font-medium text-ink-500">{label}</p>
        <p className={classNames("shrink-0 text-xs font-semibold tabular", toneText)}>{percent(value)}</p>
      </div>
      <ProgressBar className="mt-1.5" value={value} tone={tone} label={`${label}: ${percent(value)}`} />
      {detail ? <p className="mt-1.5 text-xs text-ink-500">{detail}</p> : null}
    </div>
  );
}
