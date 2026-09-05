import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ArrowUpRight, ChartNoAxesCombined, Layers3, WalletCards } from "lucide-react";
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
    <main className="flex min-h-dvh items-center justify-center bg-surface-muted px-4 py-8 sm:px-8">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-[1.75rem] border border-ink-200/80 bg-surface shadow-lift lg:min-h-[620px] lg:grid-cols-[1.05fr_1fr]">
        <section className="relative flex flex-col overflow-hidden bg-primary-900 p-7 text-white sm:p-10 lg:p-12">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl border border-white/20 bg-white/10">
              <WalletCards className="size-5" aria-hidden="true" />
            </span>
            <span className="text-lg font-semibold tracking-tight">OpenFinance</span>
          </div>
          <div className="my-9 max-w-sm lg:my-auto lg:py-16">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary-200">Clareza para decidir</p>
            <h1 className="mt-4 text-3xl font-semibold leading-[1.2] tracking-tight sm:text-4xl">Seu dinheiro.<br />Uma visão completa.</h1>
            <p className="mt-5 text-sm leading-7 text-primary-100/80">Acompanhe o presente, organize seus compromissos e planeje os próximos meses em um só lugar.</p>
          </div>
          <div className="hidden grid-cols-2 gap-4 border-t border-white/15 pt-6 lg:grid">
            <div>
              <ChartNoAxesCombined className="mb-3 size-5 text-primary-200" aria-hidden="true" />
              <p className="text-xs font-semibold">Tudo conectado</p>
              <p className="mt-1 text-xs leading-relaxed text-primary-100/65">Contas, cartões e histórico.</p>
            </div>
            <div>
              <Layers3 className="mb-3 size-5 text-primary-200" aria-hidden="true" />
              <p className="text-xs font-semibold">Planejamento claro</p>
              <p className="mt-1 text-xs leading-relaxed text-primary-100/65">Receitas e compromissos.</p>
            </div>
          </div>
        </section>
        <Card elevation="flat" className="flex flex-col justify-center !rounded-none !border-0 p-7 sm:p-10 lg:p-12">
        <div className="mb-8">
          <span className="mb-5 flex size-11 items-center justify-center rounded-xl bg-primary-50 text-primary-700">
            <WalletCards className="size-5" aria-hidden="true" />
          </span>
          <h2 className="text-2xl font-semibold tracking-tight text-ink-900">Entre na sua conta</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">Continue de onde você parou.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5" noValidate>
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
            <p role="alert" className="rounded-control border border-danger-200 bg-danger-50 px-3 py-2.5 text-sm text-danger-700">
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
            <ArrowUpRight className="size-4" aria-hidden="true" />
          </Button>
        </form>
        </Card>
      </div>
    </main>
  );
}
