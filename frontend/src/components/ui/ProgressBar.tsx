import { classNames } from "../../lib/classNames";

interface ProgressBarProps {
  /** 0–100; values above 100 fill the track and switch to the danger color. */
  value: number;
  tone?: "primary" | "positive" | "warning" | "danger" | "neutral";
  className?: string;
  label?: string;
}

const tones = {
  primary: "bg-primary-500",
  positive: "bg-positive-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
  neutral: "bg-ink-400",
};

export function ProgressBar({ value, tone = "primary", className, label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const effectiveTone = value > 100 ? "danger" : tone;
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className={classNames("h-1.5 w-full overflow-hidden rounded-full bg-ink-100", className)}
    >
      <div
        className={classNames("h-full rounded-full transition-all duration-500 ease-swift", tones[effectiveTone])}
        style={{ width: `${value > 100 ? 100 : clamped}%` }}
      />
    </div>
  );
}
