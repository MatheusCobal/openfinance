import { categoryColor } from "../../lib/categories";
import { classNames } from "../../lib/classNames";
import { pluralCompras } from "../../lib/labels";
import { formatMoney } from "../../lib/money";

export interface CategoryBreakdownItem {
  id: string | number;
  name: string;
  total: number;
  count: number;
  color?: string | null;
  subtitle?: string | null;
  /** Optional extra line under the bar (e.g. comparison with average). */
  detail?: React.ReactNode;
}

interface CategoryBreakdownProps {
  items: CategoryBreakdownItem[];
  onSelect?: (id: string | number) => void;
  className?: string;
}

/**
 * Category list with real palette colors and proportional impact bars, so the
 * heaviest categories read instantly instead of looking like a flat list.
 */
export function CategoryBreakdown({ items, onSelect, className }: CategoryBreakdownProps) {
  const max = items.reduce((best, item) => Math.max(best, Number(item.total) || 0), 0);
  const grandTotal = items.reduce((sum, item) => sum + (Number(item.total) || 0), 0);

  return (
    <div className={classNames("grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3", className)}>
      {items.map((item) => {
        const color = categoryColor(item.name, item.color);
        const share = grandTotal > 0 ? (Number(item.total) / grandTotal) * 100 : 0;
        const widthPct = max > 0 ? Math.max((Number(item.total) / max) * 100, 4) : 0;
        const content = (
          <>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 shrink-0 rounded-[4px]"
                    style={{ background: color }}
                    aria-hidden="true"
                  />
                  <h3 className="truncate text-sm font-semibold text-ink-900">{item.name}</h3>
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {item.subtitle || pluralCompras(item.count ?? 0)} · {Math.round(share)}% do total
                </p>
              </div>
              <p className="shrink-0 text-sm font-bold tabular text-ink-900">{formatMoney(item.total)}</p>
            </div>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
              <div
                className="h-full rounded-full transition-all duration-500 ease-swift"
                style={{ width: `${widthPct}%`, background: color }}
              />
            </div>
            {item.detail ? <div className="mt-3 border-t border-ink-100 pt-2.5">{item.detail}</div> : null}
          </>
        );

        if (!onSelect) {
          return (
            <div key={String(item.id)} className="rounded-card border border-ink-200/70 bg-surface p-4 shadow-card">
              {content}
            </div>
          );
        }
        return (
          <button
            key={String(item.id)}
            type="button"
            onClick={() => onSelect(item.id)}
            className="rounded-card border border-ink-200/70 bg-surface p-4 text-left shadow-card transition duration-150 hover:-translate-y-0.5 hover:border-ink-300 hover:shadow-lift"
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}
