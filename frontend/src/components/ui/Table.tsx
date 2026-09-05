import type { TableHTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

export function Table({ className, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div
      role="region"
      aria-label={props["aria-label"] || "Tabela de dados"}
      tabIndex={0}
      className="chip-strip max-w-full overflow-x-auto focus-visible:outline-offset-[-2px]"
    >
      <table
        className={classNames(
          "w-full text-sm [&_thead]:bg-surface-muted [&_th]:whitespace-nowrap [&_th]:py-3 [&_th]:text-[10px] [&_th]:font-semibold [&_th]:uppercase [&_th]:tracking-[0.1em] [&_th]:text-ink-500 [&_td]:py-4 [&_tbody_tr]:transition-colors [&_tbody_tr:hover]:bg-primary-50/50 [&_td.text-right]:tabular",
          className,
        )}
        {...props}
      />
    </div>
  );
}
