import type { TextareaHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={classNames(
        "min-h-24 w-full rounded-control border border-ink-300 bg-surface px-3 py-2 text-sm text-ink-900 shadow-sm outline-none transition placeholder:text-ink-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100",
        className,
      )}
      {...props}
    />
  );
}
