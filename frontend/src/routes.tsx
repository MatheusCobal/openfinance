import { Navigate, createBrowserRouter } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoricoPage } from "./pages/HistoricoPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlanejamentoPage } from "./pages/PlanejamentoPage";
import { ProximosPage } from "./pages/ProximosPage";
import { RegrasPage } from "./pages/RegrasPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <Navigate to="/dashboard" replace /> },
          { path: "/dashboard", element: <DashboardPage /> },
          { path: "/planejamento", element: <PlanejamentoPage /> },
          { path: "/historico", element: <HistoricoPage /> },
          { path: "/proximos", element: <ProximosPage /> },
          { path: "/regras", element: <RegrasPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
