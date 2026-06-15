import { Check } from "lucide-react";
import { classNames } from "../../lib/classNames";

interface CheckToggleProps {
  paid: boolean;
  onToggle: () => void;
  className?: string;
}

/** Circular toggle marking a cost as paid, with an animated fill. */
export function CheckToggle({ paid, onToggle, className }: CheckToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={paid}
      title={paid ? "Marcar como não pago" : "Marcar como pago"}
      className={classNames(
        "flex size-7 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-200",
        paid
          ? "border-positive-500 bg-positive-500 text-white"
          : "border-ink-300 text-transparent hover:border-positive-400",
        className,
      )}
    >
      <Check className="size-3.5" strokeWidth={3} aria-hidden="true" />
    </button>
  );
}
