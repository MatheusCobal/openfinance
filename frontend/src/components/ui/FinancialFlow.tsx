import { classNames } from "../../lib/classNames";
import { formatMoney } from "../../lib/money";

export interface FlowSegment {
  key: string;
  label: string;
  value: number;
  color: string;
}

interface FinancialFlowProps {
  /** Total the segments are measured against (usually expected income). */
  total: number;
  segments: FlowSegment[];
  /** What remains after the segments; negative renders as overflow. */
  remainder: { label: string; value: number };
  inverse?: boolean;
  className?: string;
}

/**
 * Financial Flow — the composition of the month in one strip:
 * receita → fixos → fatura → variáveis → disponível.
 */
export function FinancialFlow({ total, segments, remainder, inverse = false, className }: FinancialFlowProps) {
  const base = Math.max(total, 0);
  const visible = segments.filter((segment) => segment.value > 0);
  const used = visible.reduce((sum, segment) => sum + segment.value, 0);
  const overflow = remainder.value < 0;
  const denominator = base > 0 ? Math.max(base, used) : used;

  const widthFor = (value: number) => (denominator > 0 ? (value / denominator) * 100 : 0);
  const remainderWidth = overflow ? 0 : widthFor(Math.max(remainder.value, 0));

  const labelText = inverse ? "text-white/60" : "text-ink-500";
  const valueText = inverse ? "text-white/90" : "text-ink-800";

  if (denominator <= 0) return null;

  return (
    <div className={className}>
      <div
        className={classNames(
          "flex h-2.5 w-full overflow-hidden rounded-full",
          inverse ? "bg-white/10" : "bg-ink-100",
        )}
        role="img"
        aria-label={`Composição do mês: ${visible
          .map((segment) => `${segment.label} ${formatMoney(segment.value)}`)
          .join(", ")}; ${remainder.label} ${formatMoney(remainder.value)}`}
      >
        {visible.map((segment) => (
          <div
            key={segment.key}
            className="h-full transition-all duration-500 ease-swift"
            style={{ width: `${widthFor(segment.value)}%`, background: segment.color }}
          />
        ))}
        {remainderWidth > 0 ? (
          <div
            className="h-full transition-all duration-500 ease-swift"
            style={{ width: `${remainderWidth}%`, background: inverse ? "rgba(52, 211, 153, 0.85)" : "#34d399" }}
          />
        ) : null}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:flex sm:flex-wrap sm:gap-x-6">
        {visible.map((segment) => (
          <div key={segment.key} className="flex min-w-0 items-start gap-1.5">
            <span
              className="mt-1 size-2 shrink-0 rounded-[3px]"
              style={{ background: segment.color }}
              aria-hidden="true"
            />
            <div className="min-w-0">
              <p className={classNames("truncate text-[11px] font-medium uppercase tracking-wide", labelText)}>
                {segment.label}
              </p>
              <p className={classNames("text-sm font-semibold tabular", valueText)}>
                {formatMoney(segment.value)}
              </p>
            </div>
          </div>
        ))}
        <div className="flex min-w-0 items-start gap-1.5">
          <span
            className={classNames("mt-1 size-2 shrink-0 rounded-[3px]", overflow ? "bg-danger-400" : "bg-positive-400")}
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className={classNames("truncate text-[11px] font-medium uppercase tracking-wide", labelText)}>
              {remainder.label}
            </p>
            <p
              className={classNames(
                "text-sm font-semibold tabular",
                overflow ? (inverse ? "text-danger-300" : "text-danger-600") : valueText,
              )}
            >
              {formatMoney(remainder.value)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
