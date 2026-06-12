import type { HTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

type Tone = "neutral" | "primary" | "positive" | "warning" | "danger" | "accent" | "inverse";

const tones: Record<Tone, string> = {
  neutral: "bg-ink-100 text-ink-700",
  primary: "bg-primary-50 text-primary-700",
  positive: "bg-positive-50 text-positive-700",
  warning: "bg-warning-50 text-warning-800",
  danger: "bg-danger-50 text-danger-700",
  accent: "bg-accent-50 text-accent-700",
  inverse: "bg-white/10 text-white/90 ring-1 ring-inset ring-white/15",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
