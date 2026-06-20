import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client";
import type { Transaction } from "../types/common";
import type {
  ExpectedIncomeEntry,
  ExpectedIncomeMonth,
  FixedCost,
  FixedCostCategory,
  FixedCostsMonth,
  FixedCostTemplate,
  PlanningMonth,
} from "../types/planejamento";

export function getPlanningMonth(yearMonth: string) {
  return apiGet<PlanningMonth>(`/planning/month/${yearMonth}`);
}

export function getFixedCostsByMonth(yearMonth: string) {
  return apiGet<FixedCostsMonth>(`/fixed-costs/by-month?year_month=${yearMonth}`);
}

export function getSpendingCapacity(yearMonth: string) {
  return apiGet(`/spending-capacity?year_month=${yearMonth}`);
}

export function setVariableBudget(yearMonth: string, category: string, targetAmount: number) {
  return apiPut<{ id: number; year_month: string; category: string; target_amount: number }>(
    "/budgets/variable",
    { year_month: yearMonth, category, target_amount: targetAmount },
  );
}

export function deleteVariableBudget(yearMonth: string, category: string) {
  return apiDelete(
    `/budgets/variable?year_month=${encodeURIComponent(yearMonth)}&category=${encodeURIComponent(category)}`,
  );
}

export function replicateVariableBudgets(
  sourceMonth: string,
  monthsAhead = 11,
  overwrite = false,
) {
  return apiPost<{ replicated: number; skipped: number; months: string[] }>(
    "/budgets/variable/replicate",
    { source_month: sourceMonth, months_ahead: monthsAhead, overwrite },
  );
}

export function listFixedCostCategories() {
  return apiGet<FixedCostCategory[]>("/fixed-cost-categories");
}

export function createFixedCostCategory(body: { name: string; color: string; sort_order: number }) {
  return apiPost<FixedCostCategory>("/fixed-cost-categories", body);
}

export function deleteFixedCostCategory(id: number) {
  return apiDelete(`/fixed-cost-categories/${id}`);
}

export function listFixedCostTemplates() {
  return apiGet<FixedCostTemplate[]>("/fixed-costs/templates");
}

export function listFixedCosts(includeInactive = false) {
  return apiGet<FixedCost[]>(`/fixed-costs${includeInactive ? "?include_inactive=true" : ""}`);
}

export function createFixedCost(body: {
  category_id: number;
  description: string;
  amount: number;
  due_day: number;
}) {
  return apiPost<FixedCost>("/fixed-costs", body);
}

export function updateFixedCost(id: number, body: Partial<FixedCost>) {
  return apiPatch<FixedCost>(`/fixed-costs/${id}`, body);
}

export function deleteFixedCost(id: number) {
  return apiDelete(`/fixed-costs/${id}`);
}

export function setFixedCostOverride(id: number, yearMonth: string, amount: number) {
  return apiPut(`/fixed-costs/${id}/overrides/${yearMonth}`, { amount });
}

export function deleteFixedCostOverride(id: number, yearMonth: string) {
  return apiDelete(`/fixed-costs/${id}/overrides/${yearMonth}`);
}

export function listFixedCostMatchCandidates(yearMonth: string) {
  return apiGet<Transaction[]>(
    `/fixed-costs/match-candidates?year_month=${encodeURIComponent(yearMonth)}`,
  );
}

export function createFixedCostMatch(costId: number, transactionId: string, yearMonth: string) {
  return apiPost(`/fixed-costs/${costId}/matches`, {
    transaction_id: transactionId,
    year_month: yearMonth,
  });
}

export function deleteFixedCostMatch(matchId: number) {
  return apiDelete(`/fixed-costs/matches/${matchId}`);
}

export function listExpectedIncome(includeInactive = false) {
  return apiGet<ExpectedIncomeEntry[]>(
    `/expected-income${includeInactive ? "?include_inactive=true" : ""}`,
  );
}

export function createExpectedIncome(body: {
  description: string;
  amount: number;
  expected_day: number;
}) {
  return apiPost<ExpectedIncomeEntry>("/expected-income", body);
}

export function updateExpectedIncome(id: number, body: Partial<ExpectedIncomeEntry>) {
  return apiPatch<ExpectedIncomeEntry>(`/expected-income/${id}`, body);
}

export function deleteExpectedIncome(id: number) {
  return apiDelete(`/expected-income/${id}`);
}

export function getExpectedIncomeByMonth(yearMonth: string) {
  return apiGet<ExpectedIncomeMonth>(`/expected-income/by-month?year_month=${yearMonth}`);
}

export function setExpectedIncomeOverride(id: number, yearMonth: string, amount: number) {
  return apiPut(`/expected-income/${id}/overrides/${yearMonth}`, { amount });
}

export function deleteExpectedIncomeOverride(id: number, yearMonth: string) {
  return apiDelete(`/expected-income/${id}/overrides/${yearMonth}`);
}
