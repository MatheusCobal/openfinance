import { Outlet } from "react-router-dom";
import { ToastProvider } from "../../hooks/useToast";
import { MobileNav } from "./MobileNav";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <ToastProvider>
      <div className="min-h-screen bg-slate-50 text-slate-950">
        <Sidebar />
        <div className="min-h-screen md:ml-60">
          <Outlet />
        </div>
        <MobileNav />
      </div>
    </ToastProvider>
  );
}
