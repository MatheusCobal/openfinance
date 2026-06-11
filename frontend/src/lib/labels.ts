/**
 * Product copy helpers — turn backend enums and raw identifiers into human,
 * financial language. Nothing here changes data; it only changes how the UI
 * speaks to the user.
 */

const CASHFLOW_TYPE_LABELS: Record<string, string> = {
  expense: "Despesa",
  income: "Entrada",
  transfer: "Transferência",
  credit_card_payment: "Pagamento de fatura",
  refund: "Estorno",
  investment: "Investimento",
  cash_withdrawal: "Saque",
  adjustment: "Ajuste",
  ignored: "Fora dos totais",
  unknown: "Sem tipo",
};

const CLASSIFICATION_SOURCE_LABELS: Record<string, string> = {
  pluggy_rule: "Classificação automática",
  system_rule: "Regra do sistema",
  user_rule: "Regra personalizada",
  manual_override: "Ajuste manual",
  fallback: "Classificação padrão",
  unclassified: "Sem classificação",
};

const INVOICE_SOURCE_LABELS: Record<string, string> = {
  pluggy_official_bill: "Fatura oficial Pluggy",
  dashboard_current_invoice: "Fatura vigente calculada",
  missing_official_bill_fallback: "Sem fatura oficial",
};

const ACCOUNT_SCOPE_LABELS: Record<string, string> = {
  ALL: "Todas as contas",
  CREDIT: "Cartão de crédito",
  BANK: "Conta bancária",
};

const AMOUNT_SIGN_LABELS: Record<string, string> = {
  any: "Qualquer valor",
  negative: "Saídas",
  positive: "Entradas",
};

export function cashflowTypeLabel(value?: string | null): string {
  if (!value) return "";
  return CASHFLOW_TYPE_LABELS[value.toLowerCase()] || value;
}

export function classificationSourceLabel(value?: string | null): string {
  if (!value) return "";
  return CLASSIFICATION_SOURCE_LABELS[value.toLowerCase()] || "";
}

export function invoiceSourceLabel(value?: string | null, fallback = "Fatura"): string {
  if (!value) return fallback;
  return INVOICE_SOURCE_LABELS[value] || fallback;
}

export function accountScopeLabel(value?: string | null): string {
  if (!value) return ACCOUNT_SCOPE_LABELS.ALL;
  return ACCOUNT_SCOPE_LABELS[value.toUpperCase()] || value;
}

export function amountSignLabel(value?: string | null): string {
  if (!value) return AMOUNT_SIGN_LABELS.any;
  return AMOUNT_SIGN_LABELS[value.toLowerCase()] || value;
}

/** "1 conta ativa" / "3 contas ativas" — simple pt-BR pluralization. */
export function pluralize(count: number, singular: string, plural: string): string {
  const formatted = count.toLocaleString("pt-BR");
  return `${formatted} ${count === 1 ? singular : plural}`;
}

export function pluralCompras(count: number): string {
  return pluralize(count, "compra", "compras");
}

export function pluralParcelas(count: number): string {
  return pluralize(count, "parcela", "parcelas");
}

export function pluralItens(count: number): string {
  return pluralize(count, "item", "itens");
}
