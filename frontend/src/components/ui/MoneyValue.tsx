import { classNames } from "../../lib/classNames";
import { formatMoney } from "../../lib/money";

interface MoneyValueProps {
  value: unknown;
  signed?: boolean;
  tone?: "auto" | "neutral" | "positive" | "negative";
  className?: string;
}

export function MoneyValue({ value, signed = false, tone = "neutral", className }: MoneyValueProps) {
  const number = Number(value) || 0;
  const prefix = signed && number > 0 ? "+" : signed && number < 0 ? "-" : "";
  const color =
    tone === "auto"
      ? number < 0
        ? "text-rose-700"
        : "text-emerald-700"
      : tone === "positive"
        ? "text-emerald-700"
        : tone === "negative"
          ? "text-rose-700"
          : "";
  return (
    <span className={classNames("tabular", color, className)}>
      {prefix}
      {formatMoney(Math.abs(number))}
    </span>
  );
}
