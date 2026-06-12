import { AlertTriangle } from "lucide-react";
import { Button } from "./Button";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
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
