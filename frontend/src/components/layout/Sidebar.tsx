import { NavLink } from "react-router-dom";
import { classNames } from "../../lib/classNames";
import { BrandIcon, NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-slate-950 md:flex">
      <div className="flex h-16 shrink-0 items-center border-b border-white/10 px-5">
        <a href="/" className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-md bg-blue-600 text-white">
            <BrandIcon className="size-4" aria-hidden="true" />
          </span>
          <span className="truncate text-sm font-semibold text-white">OpenFinance</span>
        </a>
      </div>
      <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              classNames(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-slate-800 text-white"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-100",
              )
            }
          >
            <item.icon className="size-4 shrink-0" aria-hidden="true" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
