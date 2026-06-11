import {
  BarChart3,
  CalendarClock,
  ClipboardList,
  Gauge,
  Settings2,
  WalletCards,
} from "lucide-react";

export const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: Gauge },
  { to: "/planejamento", label: "Planejamento", icon: ClipboardList },
  { to: "/proximos", label: "Próximos", icon: CalendarClock },
  { to: "/historico", label: "Histórico", icon: BarChart3 },
  { to: "/regras", label: "Regras", icon: Settings2 },
] as const;

export const BrandIcon = WalletCards;
