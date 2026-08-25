import { NavLink } from "react-router-dom";
import { classNames } from "../../lib/classNames";
import { BrandIcon, NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-white/5 bg-cockpit md:flex">
      <div className="flex h-16 shrink-0 items-center px-5">
        <a href="/" className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-control bg-primary-600 text-white shadow-sm">
            <BrandIcon className="size-4" aria-hidden="true" />
          </span>
          <span className="truncate text-sm font-semibold leading-tight text-white">OpenFinance</span>
        </a>
      </div>
      <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              classNames(
                "group relative flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm font-medium transition-colors duration-150",
                isActive
                  ? "bg-white/10 text-white"
                  : "text-ink-400 hover:bg-white/5 hover:text-ink-100",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={classNames(
                    "absolute inset-y-1.5 left-0 w-1 rounded-full bg-primary-400 transition-opacity",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                  aria-hidden="true"
                />
                <item.icon className="size-4 shrink-0" aria-hidden="true" />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
