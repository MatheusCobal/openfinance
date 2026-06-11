import { NavLink } from "react-router-dom";
import { classNames } from "../../lib/classNames";
import { NAV_ITEMS } from "./nav";

export function MobileNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-slate-200 bg-white/95 shadow-[0_-12px_30px_-24px_rgba(15,23,42,.45)] backdrop-blur md:hidden">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            classNames(
              "flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[11px] font-medium",
              isActive ? "text-blue-700" : "text-slate-500",
            )
          }
        >
          <item.icon className="size-4" aria-hidden="true" />
          <span className="max-w-full truncate">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
