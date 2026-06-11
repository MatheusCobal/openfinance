export const currency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

export function asMoneyNumber(value: unknown): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function formatMoney(value: unknown): string {
  return currency.format(asMoneyNumber(value));
}

export function percent(value: number): string {
  return `${Math.round(value).toLocaleString("pt-BR")}%`;
}
