import { classNames } from "../../lib/classNames";
import type { PlanStatusTone } from "../../lib/planning";

type DayBadgeTone = PlanStatusTone | "primary";

interface DayBadgeProps {
  /** Day of the month the cost is due. */
  day: number;
  tone?: DayBadgeTone;
  /** Square side in pixels. */
  size?: number;
  className?: string;
}

const tones: Record<DayBadgeTone, string> = {
  neutral: "bg-surface-muted text-ink-700",
  positive: "bg-positive-100 text-positive-700",
  danger: "bg-danger-100 text-danger-700",
  warning: "bg-warning-100 text-warning-800",
  primary: "bg-primary-50 text-primary-700",
};

/** Small square showing the due day, tinted by payment status. */
export function DayBadge({ day, tone = "neutral", size = 38, className }: DayBadgeProps) {
  return (
    <span
      className={classNames(
        "flex shrink-0 flex-col items-center justify-center rounded-control",
        tones[tone],
        className,
      )}
      style={{ width: size, height: size }}
      title={`Vence dia ${day}`}
    >
      <span className="text-sm font-bold leading-none tabular">{day}</span>
      <span className="mt-0.5 text-[9px] font-medium uppercase leading-none opacity-60">dia</span>
    </span>
  );
}
