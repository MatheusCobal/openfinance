import type { InputHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={classNames(
        "h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-50",
        className,
      )}
      {...props}
    />
  );
}
