import { Outlet } from "react-router-dom";
import { ToastProvider } from "../../hooks/useToast";
import { MobileNav } from "./MobileNav";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <ToastProvider>
      <div className="min-h-screen bg-surface-muted text-ink-900">
        <a href="#main-content" className="skip-link">Pular para o conteúdo</a>
        <Sidebar />
        <div className="min-h-screen min-w-0 md:ml-56 xl:ml-64">
          <Outlet />
        </div>
        <MobileNav />
      </div>
    </ToastProvider>
  );
}
