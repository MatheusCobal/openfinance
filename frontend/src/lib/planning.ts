import { asMoneyNumber } from "./money";
import type { CreditCardInvoice, PlanningMonth, PlanningOverview } from "../types/planejamento";

export const PLAN_STATUS_LABELS: Record<string, string> = {
  comfortable: "Confortável",
  healthy: "Saudável",
  tight: "Apertado",
  over: "Estourado",
  unknown: "Sem receita",
};

export function planStatusLabel(status?: string): string {
  return PLAN_STATUS_LABELS[status || "unknown"] || PLAN_STATUS_LABELS.unknown;
}

export function normalizePlanningOverview(planning?: PlanningMonth | null): PlanningOverview {
  const rawCapacity = planning?.raw?.spending_capacity || {};
  const invoice = (planning?.credit_card_invoice ||
    rawCapacity.planning_invoice ||
    {}) as CreditCardInvoice;
  const fixed = rawCapacity.fixed_costs || {
    year_month: planning?.year_month || rawCapacity.year_month || "",
    total: planning?.fixed_costs?.planned || 0,
    planned_total: planning?.fixed_costs?.planned || 0,
    actual_total: planning?.fixed_costs?.actual || 0,
    pending_total: planning?.fixed_costs?.pending || 0,
    reserved_or_actual_total: planning?.fixed_costs?.reserved_or_actual || 0,
    categories: [],
    entries: planning?.fixed_costs?.entries || [],
  };
  const expectedIncome = rawCapacity.expected_income || {
    year_month: planning?.year_month,
    total: planning?.income?.expected || 0,
    entries: planning?.income?.entries || [],
  };
  const variableBudgets = rawCapacity.variable_budgets || {
    year_month: planning?.year_month,
    summary: {
      target: planning?.variable_budgets?.planned || 0,
      target_consumed: planning?.variable_budgets?.consumed || 0,
      target_remaining: planning?.variable_budgets?.remaining || 0,
      target_overage: planning?.variable_budgets?.overage || 0,
    },
    items: planning?.variable_budgets?.items || [],
  };

  return {
    ...rawCapacity,
    year_month: planning?.year_month || rawCapacity.year_month,
    planning_invoice: invoice,
    credit_card_invoice: invoice,
    expected_income_total:
      planning?.income?.expected ?? rawCapacity.expected_income_total ?? 0,
    received_income_total:
      planning?.income?.received ?? rawCapacity.received_income_total ?? 0,
    income_to_receive: planning?.income?.to_receive ?? rawCapacity.income_to_receive ?? 0,
    fixed_cost_planned_total:
      planning?.fixed_costs?.planned ??
      rawCapacity.fixed_cost_planned_total ??
      fixed.planned_total ??
      0,
    fixed_cost_actual_total:
      planning?.fixed_costs?.actual ??
      rawCapacity.fixed_cost_actual_total ??
      fixed.actual_total ??
      0,
    fixed_cost_pending_total:
      planning?.fixed_costs?.pending ??
      rawCapacity.fixed_cost_pending_total ??
      fixed.pending_total ??
      0,
    fixed_cost_reserved_total:
      planning?.fixed_costs?.reserved_or_actual ??
      rawCapacity.fixed_cost_reserved_total ??
      fixed.reserved_or_actual_total ??
      0,
    variable_budget_total:
      planning?.variable_budgets?.planned ?? rawCapacity.variable_budget_total ?? 0,
    variable_budget_consumed:
      planning?.variable_budgets?.consumed ?? rawCapacity.variable_budget_consumed ?? 0,
    variable_budget_remaining:
      planning?.variable_budgets?.remaining ?? rawCapacity.variable_budget_remaining ?? 0,
    variable_budget_overage:
      planning?.variable_budgets?.overage ?? rawCapacity.variable_budget_overage ?? 0,
    available_to_spend:
      planning?.capacity?.available_to_spend ??
      rawCapacity.available_to_spend ??
      rawCapacity.budget_available_to_spend ??
      0,
    budget_available_to_spend:
      planning?.capacity?.available_to_spend ??
      rawCapacity.budget_available_to_spend ??
      rawCapacity.available_to_spend ??
      0,
    daily_discretionary_remaining:
      planning?.capacity?.daily_discretionary_remaining ??
      rawCapacity.daily_discretionary_remaining ??
      0,
    days_remaining_in_month:
      planning?.capacity?.days_remaining_in_month ??
      rawCapacity.days_remaining_in_month ??
      0,
    plan_status: planning?.capacity?.plan_status ?? rawCapacity.plan_status,
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
  const variableBudget = planningCapacity.variable_budget_total ?? 0;
  const planningAvailable = asMoneyNumber(
    planningCapacity.budget_available_to_spend ??
      planningCapacity.discretionary_available ??
      planningCapacity.available_to_spend,
  );
  const planningInvoiceImpact = invoiceIncludedAmount(planningCapacity);
  const currentInvoiceRawAmount = cardInvoice?.amount ?? cardInvoice?.adjusted_total;
  const hasCurrentInvoiceAmount = Number.isFinite(Number(currentInvoiceRawAmount));
  const currentInvoiceAmount = hasCurrentInvoiceAmount ? asMoneyNumber(currentInvoiceRawAmount) : 0;
  const variableUsed = planningCapacity.variable_budget_consumed ?? 0;
  const variableRemaining = variableBudget - variableUsed;

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
    currentInvoiceAmount,
    variableBudget,
    variableUsed,
    variableRemaining,
    availableToSpend,
    status,
    isFuture,
  };
}

export function normalizeTextForMatch(text: string | null | undefined): string {
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
