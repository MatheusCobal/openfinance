import type { SelectHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={classNames(
        "h-11 w-full min-w-0 cursor-pointer rounded-control border border-ink-200 bg-surface px-3.5 py-2.5 text-sm text-ink-900 shadow-sm outline-none transition-colors hover:border-ink-300 focus:border-primary-500 focus:ring-2 focus:ring-primary-100 disabled:cursor-not-allowed disabled:bg-ink-50 disabled:text-ink-400 aria-[invalid=true]:border-danger-400",
        className,
      )}
      {...props}
    />
  );
}
