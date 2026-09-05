import { NavLink } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { classNames } from "../../lib/classNames";
import { BrandIcon, NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-primary-950/10 bg-cockpit md:flex xl:w-64">
      <div className="flex h-24 shrink-0 items-center px-6 xl:px-7">
        <a href="/" className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-10 items-center justify-center rounded-xl border border-white/20 bg-white/10 text-primary-200">
            <BrandIcon className="size-5" aria-hidden="true" />
          </span>
          <span className="truncate text-base font-semibold tracking-tight text-white">OpenFinance</span>
        </a>
      </div>
      <nav aria-label="Navegação principal" className="sidebar-scroll flex-1 space-y-1.5 overflow-y-auto px-4 py-5">
        <p className="mb-4 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary-200/80">Seu financeiro</p>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              classNames(
                "group relative flex min-h-12 items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-medium transition-colors duration-150",
                isActive
                  ? "bg-white text-primary-900 shadow-sm"
                  : "text-primary-100/80 hover:bg-white/10 hover:text-white",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={classNames(
                    "absolute inset-y-4 left-0 w-0.5 rounded-full bg-primary-300 transition-opacity",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                  aria-hidden="true"
                />
                <item.icon className="size-[18px] shrink-0" aria-hidden="true" />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mx-5 mb-6 border-t border-white/15 pt-5">
        <p className="text-xs font-medium text-primary-100">Clareza para cada decisão.</p>
        <a href="/" className="mt-2 inline-flex items-center gap-1 text-xs text-primary-200/80 transition-colors hover:text-white">
          Conheça o OpenFinance <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </a>
      </div>
    </aside>
  );
}
