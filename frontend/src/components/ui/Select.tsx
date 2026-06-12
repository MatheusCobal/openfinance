import type { SelectHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={classNames(
        "h-10 w-full rounded-control border border-ink-300 bg-surface px-3 py-2 text-sm text-ink-900 shadow-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100",
        className,
      )}
      {...props}
    />
  );
}
