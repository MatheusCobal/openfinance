import { Link } from "react-router-dom";
import { ArrowLeft, Compass } from "lucide-react";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";

export function NotFoundPage() {
  return (
    <>
      <Topbar />
      <PageContainer>
        <Card className="mx-auto max-w-2xl px-6 py-16 text-center sm:py-20">
          <span className="mx-auto mb-6 inline-flex size-16 items-center justify-center rounded-2xl border border-primary-100 bg-primary-50 text-primary-600">
            <Compass className="size-7" aria-hidden="true" />
          </span>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary-700">Página não encontrada · 404</p>
          <h2 className="mt-3 text-2xl font-semibold tracking-tight text-ink-900">Vamos voltar ao seu resumo.</h2>
          <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-ink-500">Esse endereço não está disponível. Acesse o Dashboard para continuar acompanhando suas finanças.</p>
          <Link
            to="/dashboard"
            className="mt-7 inline-flex min-h-10 items-center justify-center gap-2 rounded-control border border-primary-700 bg-primary-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-800"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            Ir para o Dashboard
          </Link>
        </Card>
      </PageContainer>
    </>
  );
}
