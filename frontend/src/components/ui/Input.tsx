import type { InputHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={classNames(
        "h-10 w-full rounded-control border border-ink-300 bg-surface px-3 py-2 text-sm text-ink-900 shadow-sm outline-none transition placeholder:text-ink-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100",
        className,
      )}
      {...props}
    />
  );
}
