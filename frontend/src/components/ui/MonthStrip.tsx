import { useRef } from "react";
import { classNames } from "../../lib/classNames";
import { formatMonthLong, formatMonthShort } from "../../lib/dates";

interface MonthStripProps {
  months: string[];
  value: string | null;
  onChange: (ym: string) => void;
  /** Optional secondary line per chip (e.g. total of the month). */
  captionFor?: (ym: string) => string | null;
  className?: string;
}

export function MonthStrip({ months, value, onChange, captionFor, className }: MonthStripProps) {
  const monthRefs = useRef<Array<HTMLButtonElement | null>>([]);
  return (
    <div
      className={classNames("chip-strip flex gap-2 overflow-x-auto pb-1.5", className)}
      role="tablist"
      aria-label="Selecionar mês"
    >
      {months.map((ym, index) => {
        const active = ym === value;
        const caption = captionFor?.(ym);
        return (
          <button
            key={ym}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={formatMonthLong(ym)}
            tabIndex={active || (!months.includes(value ?? "") && index === 0) ? 0 : -1}
            ref={(element) => { monthRefs.current[index] = element; }}
            onClick={() => onChange(ym)}
            onKeyDown={(event) => {
              const next = event.key === "ArrowRight" ? (index + 1) % months.length
                : event.key === "ArrowLeft" ? (index - 1 + months.length) % months.length
                : event.key === "Home" ? 0 : event.key === "End" ? months.length - 1 : null;
              if (next === null) return;
              event.preventDefault();
              onChange(months[next]);
              monthRefs.current[next]?.focus();
            }}
            className={classNames(
              "min-h-11 shrink-0 rounded-control border px-4 py-2 text-left transition-colors duration-150",
              active
                ? "border-primary-800 bg-primary-800 text-white shadow-sm"
                : "border-ink-200 bg-surface text-ink-600 hover:border-primary-300 hover:bg-primary-50 hover:text-primary-900",
            )}
          >
            <span className="block text-sm font-semibold capitalize leading-tight">
              {formatMonthShort(ym)}
            </span>
            {caption ? (
              <span
                className={classNames(
                  "mt-1 block text-[11px] tabular leading-tight",
                  active ? "text-white/80" : "text-ink-500",
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
