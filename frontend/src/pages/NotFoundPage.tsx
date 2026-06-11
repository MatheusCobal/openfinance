import { Link } from "react-router-dom";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Card } from "../components/ui/Card";

export function NotFoundPage() {
  return (
    <>
      <Topbar subtitle="Rota não encontrada" />
      <PageContainer>
        <Card className="p-8 text-center">
          <p className="text-sm font-semibold text-slate-950">Página não encontrada.</p>
          <p className="mt-1 text-sm text-slate-500">Volte para o Dashboard para continuar.</p>
          <Link
            to="/dashboard"
            className="mt-5 inline-flex min-h-9 items-center justify-center rounded-md border border-blue-700 bg-blue-700 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-800"
          >
            Ir para Dashboard
          </Link>
        </Card>
      </PageContainer>
    </>
  );
}
