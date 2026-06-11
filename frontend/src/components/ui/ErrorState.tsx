import { Button } from "./Button";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ title = "Não foi possível carregar os dados.", message, onRetry }: ErrorStateProps) {
  return (
    <div className="rounded-lg border border-rose-100 bg-rose-50 px-4 py-10 text-center">
      <p className="text-sm font-semibold text-rose-800">{title}</p>
      <p className="mt-1 text-sm text-rose-700">{message}</p>
      {onRetry ? (
        <Button type="button" className="mt-4" variant="secondary" onClick={onRetry}>
          Tentar novamente
        </Button>
      ) : null}
    </div>
  );
}
