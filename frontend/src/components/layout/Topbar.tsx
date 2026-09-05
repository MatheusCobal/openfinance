import type { ReactNode } from "react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { CalendarDays, LogOut } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { Button } from "../ui/Button";
import { NAV_ITEMS } from "./nav";

interface TopbarProps {
  subtitle?: ReactNode;
  actions?: ReactNode;
}

function AccountControl() {
  const { user, authRequired, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!authRequired) return null;

  async function handleLogout() {
    setBusy(true);
    try {
      // On success, RequireAuth redirects to /login (status → unauthenticated).
      await logout();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {user ? (
        <span className="hidden max-w-[14rem] truncate text-xs text-ink-500 sm:inline">
          {user.email}
        </span>
      ) : null}
      <Button variant="ghost" size="sm" loading={busy} onClick={handleLogout} title="Sair">
        <LogOut className="size-4" aria-hidden="true" />
        Sair
      </Button>
    </div>
  );
}

export function Topbar({ subtitle, actions }: TopbarProps) {
  const location = useLocation();
  const active = NAV_ITEMS.find((item) => item.to === location.pathname);

  return (
    <header className="sticky top-0 z-20 border-b border-ink-200/70 bg-surface/95 px-4 py-4 backdrop-blur sm:px-6 lg:px-8 xl:px-10">
      <div className="mx-auto flex max-w-[1360px] flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary-700 md:hidden">OpenFinance</p>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900 sm:text-2xl">
            {active?.label || "Página não encontrada"}
          </h1>
          {subtitle ? <div className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-ink-600"><CalendarDays className="mt-0.5 size-3.5 shrink-0 text-primary-600" aria-hidden="true" /><span>{subtitle}</span></div> : null}
        </div>
        <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">
          {actions}
          <AccountControl />
        </div>
      </div>
    </header>
  );
}
