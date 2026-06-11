import type { HTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={classNames("rounded-lg border border-slate-200 bg-white shadow-soft", className)}
      {...props}
    />
  );
}
