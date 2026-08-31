import { asMoneyNumber } from "./money";
import type {
  CreditCardInvoice,
  PlanningMonth,
  PlanningOverview,
  VariableBudgetItem,
} from "../types/planejamento";

export type PlanStatusTone = "positive" | "warning" | "danger" | "neutral";

const PLAN_STATUS_META: Record<
  string,
  { label: string; tone: PlanStatusTone; description: string }
> = {
  comfortable: {
    label: "Saudável",
    tone: "positive",
    description: "O mês cabe no plano com folga.",
  },
  healthy: {
    label: "Saudável",
    tone: "positive",
    description: "O mês cabe no plano com folga.",
  },
  tight: {
    label: "No limite",
    tone: "warning",
    description: "Pouca margem: acompanhe os gastos variáveis de perto.",
  },
  over: {
    label: "Estourado",
    tone: "danger",
    description: "Os compromissos passaram da receita esperada.",
  },
  unknown: {
    label: "Sem receita prevista",
    tone: "neutral",
    description: "Cadastre a receita esperada para acompanhar o mês.",
  },
};

export function planStatusMeta(status?: string) {
  return PLAN_STATUS_META[status || "unknown"] || PLAN_STATUS_META.unknown;
}

export function normalizePlanningOverview(planning?: PlanningMonth | null): PlanningOverview {
  const capacity = planning?.capacity || {};
  const invoice = (planning?.credit_card_invoice || {}) as CreditCardInvoice;
  const fixed = {
    year_month: planning?.year_month || capacity.year_month || "",
    total: planning?.fixed_costs?.planned || 0,
    planned_total: planning?.fixed_costs?.planned || 0,
    actual_total: planning?.fixed_costs?.actual || 0,
    pending_total: planning?.fixed_costs?.pending || 0,
    reserved_or_actual_total: planning?.fixed_costs?.reserved_or_actual || 0,
    categories: [],
    entries: planning?.fixed_costs?.entries || [],
  };
  const expectedIncome = {
    year_month: planning?.year_month,
    total: planning?.income?.expected || 0,
    entries: planning?.income?.entries || [],
  };
  const variableBudgets = {
    year_month: planning?.year_month,
    summary: {
      target: planning?.variable_budgets?.planned || 0,
      target_consumed: planning?.variable_budgets?.consumed || 0,
      target_remaining: planning?.variable_budgets?.remaining || 0,
      target_overage: planning?.variable_budgets?.overage || 0,
    },
    items: (planning?.variable_budgets?.items || []) as VariableBudgetItem[],
    eligible_categories: [] as string[],
  };

  return {
    ...capacity,
    year_month: planning?.year_month || capacity.year_month,
    planning_invoice: invoice,
    credit_card_invoice: invoice,
    expected_income_total: planning?.income?.expected ?? capacity.expected_income_total ?? 0,
    received_income_total: planning?.income?.received ?? capacity.received_income_total ?? 0,
    income_to_receive: planning?.income?.to_receive ?? capacity.income_to_receive ?? 0,
    fixed_cost_planned_total:
      planning?.fixed_costs?.planned ??
      capacity.fixed_cost_planned_total ??
      fixed.planned_total ??
      0,
    fixed_cost_actual_total:
      planning?.fixed_costs?.actual ??
      capacity.fixed_cost_actual_total ??
      fixed.actual_total ??
      0,
    fixed_cost_pending_total:
      planning?.fixed_costs?.pending ??
      capacity.fixed_cost_pending_total ??
      fixed.pending_total ??
      0,
    fixed_cost_reserved_total:
      planning?.fixed_costs?.reserved_or_actual ??
      capacity.fixed_cost_reserved_total ??
      fixed.reserved_or_actual_total ??
      0,
    variable_budget_total: planning?.variable_budgets?.planned ?? capacity.variable_budget_total ?? 0,
    variable_budget_consumed:
      planning?.variable_budgets?.consumed ?? capacity.variable_budget_consumed ?? 0,
    variable_budget_remaining:
      planning?.variable_budgets?.remaining ?? capacity.variable_budget_remaining ?? 0,
    variable_budget_overage:
      planning?.variable_budgets?.overage ?? capacity.variable_budget_overage ?? 0,
    available_to_spend:
      capacity.available_to_spend ??
      capacity.budget_available_to_spend ??
      0,
    budget_available_to_spend:
      capacity.available_to_spend ??
      capacity.budget_available_to_spend ??
      0,
    daily_discretionary_remaining:
      capacity.daily_discretionary_remaining ?? 0,
    days_remaining_in_month:
      capacity.days_remaining_in_month ?? 0,
    plan_status: capacity.plan_status,
    fixed_costs: fixed,
    expected_income: expectedIncome,
    variable_budgets: variableBudgets,
  };
}

export function invoiceIncludedAmount(capacity: PlanningOverview): number {
  const isFuture =
    (capacity.planning_mode || (capacity.is_future_month ? "future_month" : "current_month")) ===
    "future_month";
  return isFuture
    ? asMoneyNumber(capacity.future_card_obligation_total)
    : asMoneyNumber(capacity.card_invoice_remaining_to_include);
}

export function isFuturePlanningMonth(capacity: PlanningOverview): boolean {
  return (
    (capacity.planning_mode || (capacity.is_future_month ? "future_month" : "current_month")) ===
    "future_month"
  );
}

export function dashboardAvailableToSpend(
  planningCapacity: PlanningOverview,
  cardInvoice?: CreditCardInvoice | null,
) {
  const expectedIncome = planningCapacity.expected_income_total ?? 0;
  const isFuture = isFuturePlanningMonth(planningCapacity);
  const fixedCosts = isFuture
    ? planningCapacity.fixed_cost_planned_total ?? 0
    : planningCapacity.fixed_cost_reserved_total ?? 0;
  const fixedCostsPending = planningCapacity.fixed_cost_pending_total ?? fixedCosts;
  const variableBudget = planningCapacity.variable_budget_total ?? 0;
  const planningAvailable = asMoneyNumber(
    planningCapacity.budget_available_to_spend ?? planningCapacity.available_to_spend,
  );
  const planningInvoiceImpact = invoiceIncludedAmount(planningCapacity);
  const currentInvoiceRawAmount = cardInvoice?.amount ?? cardInvoice?.adjusted_total;
  const hasCurrentInvoiceAmount = Number.isFinite(Number(currentInvoiceRawAmount));
  const currentInvoiceAmount = hasCurrentInvoiceAmount ? asMoneyNumber(currentInvoiceRawAmount) : 0;
  const variableUsed = planningCapacity.variable_budget_consumed ?? 0;

  // Same rule as the static Dashboard: Planejamento keeps its monthly capacity,
  // while Dashboard swaps only the invoice component for the operational current invoice.
  const availableToSpend = hasCurrentInvoiceAmount
    ? planningAvailable + planningInvoiceImpact - currentInvoiceAmount
    : planningAvailable;

  let status = "unknown";
  if (expectedIncome <= 0) status = "unknown";
  else if (availableToSpend > 1000) status = "comfortable";
  else if (availableToSpend >= 0) status = "tight";
  else status = "over";

  return {
    expectedIncome,
    fixedCosts,
    fixedCostsPending,
    variableBudget,
    variableUsed,
    availableToSpend,
    status,
  };
}

function normalizeTextForMatch(text: string | null | undefined): string {
  return (text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function tokenSet(value: string | null | undefined): Set<string> {
  const stopwords = new Set([
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "em",
    "com",
    "pagamento",
    "compra",
    "pix",
    "qr",
    "code",
  ]);
  return new Set(
    normalizeTextForMatch(value)
      .split(/\s+/)
      .filter((token) => token.length >= 3 && !stopwords.has(token)),
  );
}
