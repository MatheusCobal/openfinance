import type { TextareaHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={classNames(
        "min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-50",
        className,
      )}
      {...props}
    />
  );
}
