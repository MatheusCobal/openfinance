import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { WalletCards } from "lucide-react";
import { ApiError } from "../api/client";
import { AuthLoading } from "../auth/AuthLoading";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { FormField } from "../components/ui/FormField";
import { Input } from "../components/ui/Input";

interface FromState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "loading") return <AuthLoading />;
  // Already logged in (e.g. opened /login with a live session) → go to the app.
  if (status === "authenticated" || status === "disabled") {
    return <Navigate to="/dashboard" replace />;
  }

  const requested = (location.state as FromState | null)?.from?.pathname;
  const destination = requested && requested !== "/login" ? requested : "/dashboard";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(destination, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Email ou senha inválidos.");
      } else {
        setError("Não foi possível entrar. Tente novamente.");
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-muted px-4 py-10">
      <Card elevation="raised" className="w-full max-w-sm p-7">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-3 flex size-11 items-center justify-center rounded-control bg-primary-600 text-white shadow-sm">
            <WalletCards className="size-5" aria-hidden="true" />
          </span>
          <h1 className="text-lg font-bold tracking-tight text-ink-900">OpenFinance</h1>
          <p className="mt-1 text-xs text-ink-500">Entre para acessar seu cockpit financeiro.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <FormField label="Email">
            <Input
              type="email"
              name="email"
              autoComplete="username"
              autoFocus
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@exemplo.com"
            />
          </FormField>

          <FormField label="Senha">
            <Input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </FormField>

          {error ? (
            <p role="alert" className="text-xs font-medium text-danger-600">
              {error}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            className="w-full"
            loading={submitting}
            disabled={!email || !password}
          >
            Entrar
          </Button>
        </form>
      </Card>
    </div>
  );
}
