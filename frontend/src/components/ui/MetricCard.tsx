import type { ReactNode } from "react";
import { Card } from "./Card";
import { classNames } from "../../lib/classNames";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  tone?: "slate" | "blue" | "emerald" | "amber" | "rose";
}

const tones = {
  slate: "bg-slate-100 text-slate-700",
  blue: "bg-blue-50 text-blue-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  rose: "bg-rose-50 text-rose-700",
};

export function MetricCard({ label, value, subtitle, icon, tone = "slate" }: MetricCardProps) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <div className="mt-2 text-2xl font-bold leading-tight text-slate-950 tabular">{value}</div>
        </div>
        {icon ? (
          <span className={classNames("inline-flex size-9 items-center justify-center rounded-md", tones[tone])}>
            {icon}
          </span>
        ) : null}
      </div>
      {subtitle ? <p className="mt-2 text-xs leading-relaxed text-slate-500">{subtitle}</p> : null}
    </Card>
  );
}
