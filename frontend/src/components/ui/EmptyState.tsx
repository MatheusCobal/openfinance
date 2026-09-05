import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  detail?: string;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ title, detail, icon, action }: EmptyStateProps) {
  return (
    <div className="rounded-card border border-ink-200/80 bg-surface px-6 py-14 text-center">
      <span className="mx-auto mb-5 inline-flex size-12 items-center justify-center rounded-2xl border border-primary-100 bg-primary-50 text-primary-600" aria-hidden="true">
        {icon ?? <Inbox className="size-5" aria-hidden="true" />}
      </span>
      <p className="text-base font-semibold tracking-tight text-ink-900">{title}</p>
      {detail ? <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-500">{detail}</p> : null}
      {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
