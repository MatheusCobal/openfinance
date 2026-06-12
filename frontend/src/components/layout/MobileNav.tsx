import { NavLink } from "react-router-dom";
import { classNames } from "../../lib/classNames";
import { NAV_ITEMS } from "./nav";

export function MobileNav() {
  return (
    <nav
      aria-label="Navegação principal"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-ink-200/70 bg-surface/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-12px_30px_-24px_rgba(15,23,42,.45)] backdrop-blur md:hidden"
    >
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            classNames(
              "flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[11px] font-medium transition-colors",
              isActive ? "text-primary-700" : "text-ink-500 hover:text-ink-700",
            )
          }
        >
          {({ isActive }) => (
            <>
              <span
                className={classNames(
                  "flex h-6 w-10 items-center justify-center rounded-full transition-colors",
                  isActive ? "bg-primary-50" : "bg-transparent",
                )}
              >
                <item.icon className="size-4" aria-hidden="true" />
              </span>
              <span className="max-w-full truncate">{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
