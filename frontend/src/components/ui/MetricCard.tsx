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

export function MetricCard({ label, value, subtitle, icon, tone = "neutral" }: MetricCardProps) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink-500">{label}</p>
          <div className="mt-1.5 text-2xl font-bold leading-tight tracking-tight text-ink-900 tabular">
            {value}
          </div>
        </div>
        {icon ? (
          <span
            className={classNames(
              "inline-flex size-9 shrink-0 items-center justify-center rounded-control",
              iconTones[tone],
            )}
            aria-hidden="true"
          >
            {icon}
          </span>
        ) : null}
      </div>
      {subtitle ? <p className="mt-2 text-xs leading-relaxed text-ink-500">{subtitle}</p> : null}
    </Card>
  );
}
