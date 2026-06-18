import type { PlanStatus, Transaction } from "./common";

export interface FixedCostCategory {
  id: number;
  name: string;
  color: string;
  sort_order?: number;
  is_default?: boolean;
}

export interface FixedCost {
  id: number;
  category_id: number;
  description: string;
  amount: number;
  due_day: number;
  active: boolean;
}

export interface FixedCostTemplate {
  label: string;
  category_id: number;
  description: string;
  due_day: number;
}

export interface FixedCostMonthEntry {
  fixed_cost_id: number;
  fixed_cost_transaction_match_id?: number | null;
  category_id: number;
  category_name: string;
  category_color: string;
  description: string;
  amount: number;
  base_amount: number;
  due_day: number;
  due_date: string;
  status?: string;
  is_override?: boolean;
  match_source?: string | null;
  matched_transaction?: Transaction | null;
  [key: string]: any;
}

export interface FixedCostsMonth {
  year_month: string;
  total: number;
  planned_total?: number;
  actual_total?: number;
  pending_total?: number;
  reserved_or_actual_total?: number;
  categories?: Array<{ id: number; name: string; color: string; total: number; count: number }>;
  entries: FixedCostMonthEntry[];
}

export interface ExpectedIncomeEntry {
  id: number;
  description: string;
  amount: number;
  expected_day: number;
  active: boolean;
}

export interface ExpectedIncomeMonthEntry {
  expected_income_id: number;
  description: string;
  amount: number;
  base_amount: number;
  expected_day: number;
  is_override?: boolean;
}

export interface ExpectedIncomeMonth {
  year_month: string;
  total: number;
  entries: ExpectedIncomeMonthEntry[];
}

export interface VariableBudgetItem {
  category: string;
  target: number;
  spent: number;
  remaining: number;
  progress_percent: number | null;
  status: "ok" | "warning" | "over" | "no_target";
  transaction_count: number;
  has_target: boolean;
}

export interface PlanningOverview {
  year_month?: string;
  planning_mode?: string;
  is_future_month?: boolean;
  expected_income_total?: number;
  received_income_total?: number;
  income_to_receive?: number;
  fixed_cost_planned_total?: number;
  fixed_cost_actual_total?: number;
  fixed_cost_pending_total?: number;
  fixed_cost_reserved_total?: number;
  variable_budget_total?: number;
  variable_budget_uncommitted?: number;
  variable_budget_consumed?: number;
  variable_budget_remaining?: number;
  variable_budget_overage?: number;
  variable_budget_reserved?: number;
  unbudgeted_variable_spent?: number;
  future_card_obligation_total?: number;
  future_card_obligation_source?: string;
  future_card_obligation_count?: number;
  future_card_obligation_display_month?: string | null;
  card_invoice_remaining_to_include?: number;
  card_invoice_official_total?: number;
  card_invoice_gross_total?: number;
  card_invoice_source?: string;
  card_invoice_current_open_total?: number;
  card_invoice_current_open_source?: string;
  card_invoice_current_open_label?: string;
  card_invoice_cycle_start?: string | null;
  card_invoice_cycle_end?: string | null;
  bank_outflows_total?: number;
  available_to_spend?: number;
  budget_available_to_spend?: number;
  discretionary_available?: number;
  remaining_after_plan?: number;
  remaining_after_invoice?: number;
  daily_discretionary_remaining?: number;
  days_remaining_in_month?: number;
  plan_status?: PlanStatus;
  fixed_costs?: FixedCostsMonth;
  expected_income?: { total?: number; entries?: unknown[] };
  variable_budgets?: {
    summary?: Record<string, number>;
    items?: VariableBudgetItem[];
    eligible_categories?: string[];
  };
  planning_invoice?: CreditCardInvoice;
  credit_card_invoice?: CreditCardInvoice;
  raw?: { spending_capacity?: Partial<PlanningOverview> };
  [key: string]: any;
}

export interface PlanningMonth {
  year_month: string;
  raw?: { spending_capacity?: Partial<PlanningOverview> };
  capacity?: Partial<PlanningOverview>;
  income?: {
    expected?: number;
    received?: number;
    to_receive?: number;
    entries?: unknown[];
  };
  fixed_costs?: {
    planned?: number;
    actual?: number;
    pending?: number;
    reserved_or_actual?: number;
    entries?: FixedCostMonthEntry[];
  };
  variable_budgets?: {
    planned?: number;
    consumed?: number;
    remaining?: number;
    overage?: number;
    items?: unknown[];
  };
  credit_card_invoice?: CreditCardInvoice;
  [key: string]: any;
}

export interface CreditCardInvoice {
  amount?: number;
  adjusted_total?: number;
  remaining_amount?: number;
  source?: string;
  source_label?: string;
  is_estimated?: boolean;
  due_dates?: string[];
  cards?: Array<Record<string, any>>;
  categories?: InvoiceCategory[];
  raw_purchase_transactions?: Transaction[];
  reconciliation?: Record<string, any>;
  year_month?: string;
  [key: string]: any;
}

export interface InvoiceCategory {
  id: string | number;
  name: string;
  color?: string;
  total: number;
  count: number;
  transactions?: Transaction[];
  [key: string]: any;
}
