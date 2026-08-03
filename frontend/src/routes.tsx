import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { AuthLoading } from "./auth/AuthLoading";
import { AppShell } from "./components/layout/AppShell";

const DashboardPage = lazy(async () => ({
  default: (await import("./pages/DashboardPage")).DashboardPage,
}));
const HistoricoPage = lazy(async () => ({
  default: (await import("./pages/HistoricoPage")).HistoricoPage,
}));
const LoginPage = lazy(async () => ({ default: (await import("./pages/LoginPage")).LoginPage }));
const NotFoundPage = lazy(async () => ({
  default: (await import("./pages/NotFoundPage")).NotFoundPage,
}));
const PlanejamentoPage = lazy(async () => ({
  default: (await import("./pages/PlanejamentoPage")).PlanejamentoPage,
}));
const ProximosPage = lazy(async () => ({
  default: (await import("./pages/ProximosPage")).ProximosPage,
}));

function suspended(page: ReactNode) {
  return <Suspense fallback={<AuthLoading />}>{page}</Suspense>;
}

export const router = createBrowserRouter([
  { path: "/login", element: suspended(<LoginPage />) },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <Navigate to="/dashboard" replace /> },
          { path: "/dashboard", element: suspended(<DashboardPage />) },
          { path: "/planejamento", element: suspended(<PlanejamentoPage />) },
          { path: "/historico", element: suspended(<HistoricoPage />) },
          { path: "/proximos", element: suspended(<ProximosPage />) },
          { path: "*", element: suspended(<NotFoundPage />) },
        ],
      },
    ],
  },
]);
