import type { TableHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Table({ className, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto">
      <table className={classNames("w-full text-sm", className)} {...props} />
    </div>
  );
}
