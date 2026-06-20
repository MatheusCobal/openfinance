import { AlertTriangle } from "lucide-react";
import { Button } from "./Button";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

interface StaleDataWarningProps {
  message: string;
  loading?: boolean;
  onRetry: () => void;
}

export function ErrorState({ title = "Não foi possível carregar os dados.", message, onRetry }: ErrorStateProps) {
  return (
    <div className="rounded-card border border-danger-200 bg-danger-50 px-6 py-10 text-center">
      <span className="mx-auto mb-3 inline-flex size-10 items-center justify-center rounded-full bg-danger-100 text-danger-600">
        <AlertTriangle className="size-5" aria-hidden="true" />
      </span>
      <p className="text-sm font-semibold text-danger-800">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-danger-700">{message}</p>
      {onRetry ? (
        <Button type="button" className="mt-4" variant="secondary" onClick={onRetry}>
          Tentar novamente
        </Button>
      ) : null}
    </div>
  );
}

export function StaleDataWarning({ message, loading = false, onRetry }: StaleDataWarningProps) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-control border border-danger-200 bg-danger-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex min-w-0 items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger-600" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-danger-800">Não foi possível atualizar os dados.</p>
          <p className="mt-0.5 text-xs leading-relaxed text-danger-700">
            {message} Os valores abaixo são da última atualização bem-sucedida.
          </p>
        </div>
      </div>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        loading={loading}
        className="shrink-0 self-start sm:self-auto"
        onClick={onRetry}
      >
        Tentar novamente
      </Button>
    </div>
  );
}
