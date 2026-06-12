import { classNames } from "../../lib/classNames";
import type { PlanStatusTone } from "../../lib/planning";

interface StatusPillProps {
  label: string;
  tone?: PlanStatusTone;
  /** Render on dark (cockpit) surfaces. */
  inverse?: boolean;
  className?: string;
}

const dotTones: Record<PlanStatusTone, string> = {
  positive: "bg-positive-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
  neutral: "bg-ink-400",
};

const lightTones: Record<PlanStatusTone, string> = {
  positive: "bg-positive-50 text-positive-700 ring-positive-200",
  warning: "bg-warning-50 text-warning-800 ring-warning-200",
  danger: "bg-danger-50 text-danger-700 ring-danger-200",
  neutral: "bg-ink-100 text-ink-600 ring-ink-200",
};

export function StatusPill({ label, tone = "neutral", inverse = false, className }: StatusPillProps) {
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        inverse ? "bg-white/10 text-white ring-white/15" : lightTones[tone],
        className,
      )}
    >
      <span className={classNames("size-1.5 rounded-full", dotTones[tone])} aria-hidden="true" />
      {label}
    </span>
  );
}
