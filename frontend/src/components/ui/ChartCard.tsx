import type { ReactNode } from "react";
import { Card } from "./Card";

interface ChartCardProps {
  title: string;
  subtitle?: string;
  /** Legend chips, filters or totals aligned to the right of the title. */
  aside?: ReactNode;
  children: ReactNode;
}

export function ChartCard({ title, subtitle, aside, children }: ChartCardProps) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p> : null}
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
      <div className="mt-4 h-64 sm:h-72">{children}</div>
    </Card>
  );
}
