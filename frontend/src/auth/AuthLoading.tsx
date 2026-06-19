import { Loader2 } from "lucide-react";

/** Full-screen spinner shown while the initial /auth/me check is in flight. */
export function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-muted">
      <Loader2 className="size-6 animate-spin text-ink-400" aria-hidden="true" />
      <span className="sr-only">Carregando…</span>
    </div>
  );
}
