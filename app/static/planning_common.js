'use strict';

// ──────────────────────────────────────────────────────────────────────────
// Shared planning helpers.
//
// Single source of truth for the financial normalization used by BOTH the
// Planejamento ("Visão do mês") screen and the Dashboard. Loaded as a plain
// <script> before planejamento.js / dashboard.js, so every symbol here lives
// on the global scope and must NOT be redeclared in those files.
//
// Keep this file free of DOM access and page-specific state — pure helpers
// only, so the Dashboard is a read-only presentation of the same numbers.
// ──────────────────────────────────────────────────────────────────────────

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MONTH_LABELS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

function currentYearMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function getDefaultPlanningMonth() {
  return shiftYearMonth(currentYearMonth(), 1);
}

function shiftYearMonth(ym, offset) {
  const [year, month] = ym.split('-').map(Number);
  const zeroBased = year * 12 + (month - 1) + offset;
  return `${String(Math.floor(zeroBased / 12)).padStart(4, '0')}-${String((zeroBased % 12) + 1).padStart(2, '0')}`;
}

function formatMonthShort(ym) {
  const [year, month] = ym.split('-').map(Number);
  return `${MONTH_LABELS[month - 1]}/${String(year).slice(2)}`;
}

function asMoneyNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function normalizePlanningOverview(planning) {
  const rawCapacity = planning?.raw?.spending_capacity || {};
  const invoice = planning?.credit_card_invoice || rawCapacity.planning_invoice || {};
  const fixed = rawCapacity.fixed_costs || {
    year_month: planning?.year_month,
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
    expected_income_total: planning?.income?.expected ?? rawCapacity.expected_income_total ?? 0,
    received_income_total: planning?.income?.received ?? rawCapacity.received_income_total ?? 0,
    income_to_receive: planning?.income?.to_receive ?? rawCapacity.income_to_receive ?? 0,
    fixed_cost_planned_total: planning?.fixed_costs?.planned ?? rawCapacity.fixed_cost_planned_total ?? fixed.planned_total ?? 0,
    fixed_cost_actual_total: planning?.fixed_costs?.actual ?? rawCapacity.fixed_cost_actual_total ?? fixed.actual_total ?? 0,
    fixed_cost_pending_total: planning?.fixed_costs?.pending ?? rawCapacity.fixed_cost_pending_total ?? fixed.pending_total ?? 0,
    fixed_cost_reserved_total: planning?.fixed_costs?.reserved_or_actual ?? rawCapacity.fixed_cost_reserved_total ?? fixed.reserved_or_actual_total ?? 0,
    variable_budget_total: planning?.variable_budgets?.planned ?? rawCapacity.variable_budget_total ?? 0,
    variable_budget_consumed: planning?.variable_budgets?.consumed ?? rawCapacity.variable_budget_consumed ?? 0,
    variable_budget_remaining: planning?.variable_budgets?.remaining ?? rawCapacity.variable_budget_remaining ?? 0,
    variable_budget_overage: planning?.variable_budgets?.overage ?? rawCapacity.variable_budget_overage ?? 0,
    available_to_spend: planning?.capacity?.available_to_spend ?? rawCapacity.available_to_spend ?? rawCapacity.budget_available_to_spend ?? 0,
    budget_available_to_spend: planning?.capacity?.available_to_spend ?? rawCapacity.budget_available_to_spend ?? rawCapacity.available_to_spend ?? 0,
    daily_discretionary_remaining: planning?.capacity?.daily_discretionary_remaining ?? rawCapacity.daily_discretionary_remaining ?? 0,
    days_remaining_in_month: planning?.capacity?.days_remaining_in_month ?? rawCapacity.days_remaining_in_month ?? 0,
    plan_status: planning?.capacity?.plan_status ?? rawCapacity.plan_status,
    fixed_costs: fixed,
    expected_income: expectedIncome,
    variable_budgets: variableBudgets,
  };
}

function invoiceIncludedAmount(capacity) {
  const isFuture = (capacity.planning_mode || (capacity.is_future_month ? 'future_month' : 'current_month')) === 'future_month';
  return isFuture
    ? asMoneyNumber(capacity.future_card_obligation_total)
    : asMoneyNumber(capacity.card_invoice_remaining_to_include);
}

// Plan-status badge label mapping shared across screens. (Planejamento's
// capacity flow keeps its own inline copy with colour classes; this is the
// canonical label source for the Dashboard.)
const PLAN_STATUS_LABELS = {
  comfortable: 'Confortável',
  healthy: 'Saudável',
  tight: 'Apertado',
  over: 'Estourado',
  unknown: 'Sem receita',
};

function planStatusLabel(status) {
  return PLAN_STATUS_LABELS[status] || PLAN_STATUS_LABELS.unknown;
}

// Explicit namespace — preferred entry point for new code.
// The top-level declarations above remain as aliases so the existing bundles
// (dashboard.js, planejamento.js) continue working without a full rewrite.
window.OpenFinancePlanning = {
  currency,
  MONTH_LABELS,
  currentYearMonth,
  getDefaultPlanningMonth,
  shiftYearMonth,
  formatMonthShort,
  asMoneyNumber,
  normalizePlanningOverview,
  invoiceIncludedAmount,
  PLAN_STATUS_LABELS,
  planStatusLabel,
};
