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
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight text-ink-900">{title}</h2>
          {subtitle ? <p className="mt-1 text-xs leading-relaxed text-ink-500">{subtitle}</p> : null}
        </div>
        {aside ? <div className="max-w-full">{aside}</div> : null}
      </div>
      <div className="mt-6 h-64 sm:h-72">{children}</div>
    </Card>
  );
}
