export function LoadingState({ label = "Carregando dados..." }: { label?: string }) {
  return (
    <div className="space-y-5" role="status" aria-label={label} aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
        {[0, 1, 2].map((item) => (
          <div key={item} className={`rounded-card border border-ink-200/80 bg-surface p-6 ${item === 2 ? "hidden lg:block" : ""}`}>
            <div className="h-3 w-24 animate-pulse rounded bg-ink-200/70 motion-reduce:animate-none" />
            <div className="mt-4 h-8 w-36 animate-pulse rounded bg-ink-200/60 motion-reduce:animate-none" />
            <div className="mt-5 h-2.5 w-28 animate-pulse rounded bg-ink-100 motion-reduce:animate-none" />
          </div>
        ))}
      </div>
      <div className="rounded-card border border-ink-200/80 bg-surface p-6" aria-hidden="true">
        <div className="h-4 w-40 animate-pulse rounded bg-ink-200/60 motion-reduce:animate-none" />
        <div className="mt-6 h-48 animate-pulse rounded-xl bg-surface-muted motion-reduce:animate-none" />
      </div>
      <p className="text-center text-xs text-ink-500">{label}</p>
    </div>
  );
}
