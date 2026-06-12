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
    <div className="rounded-card border border-dashed border-ink-200 bg-surface px-6 py-12 text-center">
      <span className="mx-auto mb-3 inline-flex size-10 items-center justify-center rounded-full bg-ink-100 text-ink-400">
        {icon ?? <Inbox className="size-5" aria-hidden="true" />}
      </span>
      <p className="text-sm font-semibold text-ink-700">{title}</p>
      {detail ? <p className="mx-auto mt-1 max-w-md text-sm text-ink-500">{detail}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
