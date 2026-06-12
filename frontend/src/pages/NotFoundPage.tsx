import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";

export function NotFoundPage() {
  return (
    <>
      <Topbar subtitle="Página não encontrada" />
      <PageContainer>
        <Card className="p-10 text-center">
          <span className="mx-auto mb-3 inline-flex size-10 items-center justify-center rounded-full bg-ink-100 text-ink-400">
            <Compass className="size-5" aria-hidden="true" />
          </span>
          <p className="text-sm font-semibold text-ink-900">Essa página não existe.</p>
          <p className="mt-1 text-sm text-ink-500">Volte para o Dashboard para continuar.</p>
          <Link
            to="/dashboard"
            className="mt-5 inline-flex min-h-9 items-center justify-center rounded-control border border-primary-600 bg-primary-600 px-3.5 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700"
          >
            Ir para o Dashboard
          </Link>
        </Card>
      </PageContainer>
    </>
  );
}
