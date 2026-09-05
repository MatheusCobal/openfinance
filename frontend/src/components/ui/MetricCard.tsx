import type { ReactNode } from "react";
import { Card } from "./Card";
import { classNames } from "../../lib/classNames";

type Tone = "neutral" | "primary" | "positive" | "warning" | "danger";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
}

const iconTones: Record<Tone, string> = {
  neutral: "bg-ink-100 text-ink-600",
  primary: "bg-primary-50 text-primary-600",
  positive: "bg-positive-50 text-positive-600",
  warning: "bg-warning-50 text-warning-600",
  danger: "bg-danger-50 text-danger-600",
};

const valueTones: Record<Tone, string> = {
  neutral: "text-ink-900",
  primary: "text-primary-900",
  positive: "text-positive-700",
  warning: "text-warning-800",
  danger: "text-danger-700",
};

export function MetricCard({ label, value, subtitle, icon, tone = "neutral" }: MetricCardProps) {
  return (
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium leading-relaxed text-ink-500">{label}</p>
          <div className={classNames("mt-2 break-words text-[clamp(1.5rem,2.3vw,2rem)] font-semibold leading-tight tracking-tight tabular", valueTones[tone])}>
            {value}
          </div>
        </div>
        {icon ? (
          <span
            className={classNames(
              "inline-flex size-10 shrink-0 items-center justify-center rounded-xl",
              iconTones[tone],
            )}
            aria-hidden="true"
          >
            {icon}
          </span>
        ) : null}
      </div>
      {subtitle ? <div className="mt-3 border-t border-ink-100 pt-3 text-xs leading-relaxed text-ink-500">{subtitle}</div> : null}
    </Card>
  );
}
