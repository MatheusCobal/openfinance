import { classNames } from "../../lib/classNames";
import { formatMonthShort } from "../../lib/dates";

interface MonthStripProps {
  months: string[];
  value: string | null;
  onChange: (ym: string) => void;
  /** Optional secondary line per chip (e.g. total of the month). */
  captionFor?: (ym: string) => string | null;
  className?: string;
}

export function MonthStrip({ months, value, onChange, captionFor, className }: MonthStripProps) {
  return (
    <div
      className={classNames("chip-strip flex gap-1.5 overflow-x-auto pb-1.5", className)}
      role="tablist"
      aria-label="Selecionar mês"
    >
      {months.map((ym) => {
        const active = ym === value;
        const caption = captionFor?.(ym);
        return (
          <button
            key={ym}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(ym)}
            className={classNames(
              "shrink-0 rounded-control border px-3 py-1.5 text-left transition-colors duration-150",
              active
                ? "border-ink-900 bg-ink-900 text-white shadow-sm"
                : "border-ink-200 bg-surface text-ink-600 hover:border-ink-300 hover:text-ink-900",
            )}
          >
            <span className="block text-sm font-semibold capitalize leading-tight">
              {formatMonthShort(ym)}
            </span>
            {caption ? (
              <span
                className={classNames(
                  "block text-[11px] tabular leading-tight",
                  active ? "text-white/70" : "text-ink-400",
                )}
              >
                {caption}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
