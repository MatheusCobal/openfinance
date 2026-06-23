import {
  Banknote,
  BookOpen,
  Building2,
  Car,
  CreditCard,
  Droplets,
  Dumbbell,
  GraduationCap,
  Heart,
  HeartPulse,
  Home,
  Landmark,
  PawPrint,
  PiggyBank,
  Plane,
  Receipt,
  ShoppingBag,
  ShoppingCart,
  Sparkles,
  TrendingDown,
  Tv,
  Users,
  Utensils,
  Wifi,
  Zap,
  type LucideIcon,
} from "lucide-react";

interface CatAvatarProps {
  /** Category name — drives the icon glyph. */
  category?: string | null;
  /** Resolved category color (hex). Used for the tinted background + glyph. */
  color: string;
  size?: number;
  radius?: number;
}

/** Pick a representative glyph from the category name (accent-insensitive). */
function iconForCategory(name?: string | null): LucideIcon {
  const key = (name || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
  if (key.includes("morad") || key.includes("casa") || key.includes("aluguel")) return Home;
  if (key.includes("condom")) return Building2;
  if (key.includes("financiam") || key.includes("hipoteca") || key.includes("mortgage")) return Landmark;
  if (key.includes("emprest")) return Banknote;
  if (key.includes("divida") || key.includes("debito")) return TrendingDown;
  if (key.includes("saude") || key.includes("plano")) return HeartPulse;
  if (key.includes("academia") || key.includes("fitness") || key.includes("ginasio")) return Dumbbell;
  if (key.includes("assinatura") || key.includes("streaming")) return Tv;
  if (key.includes("internet") || key.includes("telefon") || key.includes("celular")) return Wifi;
  if (key.includes("transporte") || key.includes("carro") || key.includes("seguro")) return Car;
  if (key.includes("viagem") || key.includes("viage")) return Plane;
  if (key.includes("educac") || key.includes("faculdade") || key.includes("curso")) return GraduationCap;
  if (key.includes("livro") || key.includes("leitura")) return BookOpen;
  if (key.includes("mercado") || key.includes("supermerc")) return ShoppingCart;
  if (key.includes("aliment") || key.includes("comida") || key.includes("restaurante")) return Utensils;
  if (key.includes("compra")) return ShoppingBag;
  if (key.includes("lazer") || key.includes("beleza")) return Sparkles;
  if (key.includes("invest") || key.includes("poupan")) return PiggyBank;
  if (key.includes("imposto") || key.includes("taxa")) return Receipt;
  if (key.includes("luz") || key.includes("energia") || key.includes("eletric")) return Zap;
  if (key.includes("agua") || key.includes("saneam")) return Droplets;
  if (key.includes("pet") || key.includes("racao") || key.includes("animal") || key.includes("canil")) return PawPrint;
  if (key.includes("diarista") || key.includes("faxin") || key.includes("empregad") || key.includes("domest")) return Users;
  if (key.includes("esposa") || key.includes("marido") || key.includes("conjuge") || key.includes("famil")) return Heart;
  return CreditCard;
}

/** Rounded tile tinted with the category color, holding a category glyph. */
export function CatAvatar({ category, color, size = 38, radius = 12 }: CatAvatarProps) {
  const Glyph = iconForCategory(category);
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size, borderRadius: radius, background: `${color}1A`, color }}
      aria-hidden="true"
    >
      <Glyph style={{ width: size * 0.45, height: size * 0.45 }} strokeWidth={1.8} />
    </span>
  );
}
