import { ChevronRight } from "lucide-react";
import { categoryColor } from "../../lib/categories";
import { classNames } from "../../lib/classNames";
import { pluralCompras } from "../../lib/labels";
import { formatMoney } from "../../lib/money";
import { CatAvatar } from "./CatAvatar";

interface CategoryBreakdownItem {
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
  const max = items.reduce((best, item) => Math.max(best, Math.abs(Number(item.total) || 0)), 0);
  const grandTotal = items.reduce((sum, item) => sum + Math.abs(Number(item.total) || 0), 0);

  return (
    <div className={classNames("grid grid-cols-1 gap-px overflow-hidden rounded-card border border-ink-200/80 bg-ink-100 shadow-card lg:grid-cols-2", className)}>
      {items.map((item) => {
        const color = categoryColor(item.name, item.color);
        const absoluteTotal = Math.abs(Number(item.total) || 0);
        const share = grandTotal > 0 ? (absoluteTotal / grandTotal) * 100 : 0;
        const widthPct = max > 0 ? Math.max((absoluteTotal / max) * 100, 4) : 0;
        const content = (
          <>
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <CatAvatar category={item.name} color={color} size={36} radius={10} />
                <div className="min-w-0">
                  <h3 className="break-words text-sm font-semibold leading-snug text-ink-900">{item.name}</h3>
                  <p className="mt-1 text-xs text-ink-500">
                    {item.subtitle || pluralCompras(item.count ?? 0)} · {Math.round(share)}% do total
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <p className="text-sm font-semibold tabular text-ink-900">{formatMoney(item.total)}</p>
                {onSelect ? <ChevronRight className="size-3.5 text-ink-400" aria-hidden="true" /> : null}
              </div>
            </div>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
              <div
                className="h-full rounded-full transition-all duration-500 ease-swift motion-reduce:transition-none"
                style={{ width: `${widthPct}%`, background: color }}
              />
            </div>
            {item.detail ? <div className="mt-3 border-t border-ink-100 pt-2.5">{item.detail}</div> : null}
          </>
        );

        if (!onSelect) {
          return (
            <div key={String(item.id)} className="min-w-0 bg-surface p-5">
              {content}
            </div>
          );
        }
        return (
          <button
            key={String(item.id)}
            type="button"
            onClick={() => onSelect(item.id)}
            className="min-w-0 bg-surface p-5 text-left transition-colors duration-150 hover:bg-primary-50"
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}
