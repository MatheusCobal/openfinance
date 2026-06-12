import type { ReactNode } from "react";
import { classNames } from "../../lib/classNames";

type Tone = "primary" | "positive" | "warning" | "danger" | "neutral";

interface InsightCardProps {
  icon: ReactNode;
  title: string;
  body: ReactNode;
  tone?: Tone;
  className?: string;
}

const iconTones: Record<Tone, string> = {
  primary: "bg-primary-50 text-primary-600",
  positive: "bg-positive-50 text-positive-600",
  warning: "bg-warning-50 text-warning-600",
  danger: "bg-danger-50 text-danger-600",
  neutral: "bg-ink-100 text-ink-600",
};

/** Small, useful reading of the month — one fact, one suggestion. */
export function InsightCard({ icon, title, body, tone = "neutral", className }: InsightCardProps) {
  return (
    <div
      className={classNames(
        "flex items-start gap-3 rounded-card border border-ink-200/70 bg-surface p-4 shadow-card",
        className,
      )}
    >
      <span
        className={classNames(
          "mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-control",
          iconTones[tone],
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink-900">{title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-500">{body}</p>
      </div>
    </div>
  );
}
