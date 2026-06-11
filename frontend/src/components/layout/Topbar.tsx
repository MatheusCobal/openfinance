import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { BrandIcon, NAV_ITEMS } from "./nav";

interface TopbarProps {
  subtitle?: ReactNode;
  actions?: ReactNode;
}

export function Topbar({ subtitle, actions }: TopbarProps) {
  const location = useLocation();
  const active = NAV_ITEMS.find((item) => item.to === location.pathname) || NAV_ITEMS[0];

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-6 lg:px-8">
      <div className="flex min-h-10 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <Link to="/dashboard" className="mb-1 flex items-center gap-2 text-xs font-semibold text-slate-500 md:hidden">
            <span className="inline-flex size-6 items-center justify-center rounded bg-blue-600 text-white">
              <BrandIcon className="size-3.5" aria-hidden="true" />
            </span>
            OpenFinance
          </Link>
          <h1 className="text-lg font-bold text-slate-950">{active.label}</h1>
          {subtitle ? <div className="mt-0.5 truncate text-xs text-slate-500">{subtitle}</div> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
