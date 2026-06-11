interface EmptyStateProps {
  title: string;
  detail?: string;
}

export function EmptyState({ title, detail }: EmptyStateProps) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-12 text-center">
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {detail ? <p className="mt-1 text-sm text-slate-400">{detail}</p> : null}
    </div>
  );
}
