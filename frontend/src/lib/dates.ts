const MONTH_LABELS = [
  "jan",
  "fev",
  "mar",
  "abr",
  "mai",
  "jun",
  "jul",
  "ago",
  "set",
  "out",
  "nov",
  "dez",
];

const monthShortFormatter = new Intl.DateTimeFormat("pt-BR", {
  month: "short",
  year: "2-digit",
});

const monthLongFormatter = new Intl.DateTimeFormat("pt-BR", {
  month: "long",
  year: "numeric",
});

const dayFormatter = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
});

export function currentYearMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftYearMonth(ym: string, offset: number): string {
  const [year, month] = ym.split("-").map(Number);
  const zeroBased = year * 12 + (month - 1) + offset;
  return `${String(Math.floor(zeroBased / 12)).padStart(4, "0")}-${String(
    (zeroBased % 12) + 1,
  ).padStart(2, "0")}`;
}

export function getDefaultPlanningMonth(): string {
  return shiftYearMonth(currentYearMonth(), 1);
}

export function formatMonthShort(ym: string): string {
  const [year, month] = ym.split("-").map(Number);
  if (!year || !month) return ym;
  return `${MONTH_LABELS[month - 1]}/${String(year).slice(2)}`;
}

export function formatMonthCompact(ym: string): string {
  const [year, month] = ym.split("-").map(Number);
  if (!year || !month) return ym;
  return monthShortFormatter.format(new Date(year, month - 1, 1));
}

export function formatMonthLong(ym: string): string {
  const [year, month] = ym.split("-").map(Number);
  if (!year || !month) return ym;
  const label = monthLongFormatter.format(new Date(year, month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function formatDayLabel(isoDate?: string | null): string {
  if (!isoDate) return "-";
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  return dayFormatter.format(new Date(year, month - 1, day));
}

export function monthWindow(start = getDefaultPlanningMonth(), size = 6): string[] {
  return Array.from({ length: size }, (_, index) => shiftYearMonth(start, index));
}
