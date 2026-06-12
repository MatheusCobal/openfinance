export function LoadingState({ label = "Carregando dados..." }: { label?: string }) {
  return (
    <div className="space-y-4" role="status" aria-label={label}>
      <div className="h-44 animate-pulse rounded-card bg-ink-200/50" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="h-28 animate-pulse rounded-card bg-ink-200/40" />
        <div className="h-28 animate-pulse rounded-card bg-ink-200/40" />
        <div className="hidden h-28 animate-pulse rounded-card bg-ink-200/40 lg:block" />
      </div>
      <p className="text-center text-sm text-ink-400">{label}</p>
    </div>
  );
}
