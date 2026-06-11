import type { SelectHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={classNames(
        "h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-50",
        className,
      )}
      {...props}
    />
  );
}
