export type ID = string | number;

export interface ApiErrorShape {
  detail?: string | Array<{ msg?: string; loc?: string[]; type?: string }>;
  message?: string;
}

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export type PlanStatus = "comfortable" | "healthy" | "tight" | "over" | "unknown" | string;

export type CashflowType = "INCOME" | "EXPENSE" | "TRANSFER" | "CREDIT_CARD_PAYMENT" | string;

export interface ClassificationOptions {
  internal_categories: string[];
  cashflow_types: string[];
}

export interface Transaction {
  id: string;
  date: string;
  amount: number;
  description: string;
  account_id?: string;
  account_name?: string;
  account_type?: string;
  category?: string;
  pluggy_category?: string;
  pluggy_subcategory?: string;
  pluggy_type?: string;
  internal_category?: string | null;
  effective_category?: string | null;
  resolved_category?: string | null;
  credit_category?: string | null;
  custom_category_name?: string | null;
  cashflow_type?: CashflowType | null;
  ignored_from_totals?: boolean | null;
  classification_source?: string | null;
  classification_confidence?: string | null;
  installment_number?: number | null;
  total_installments?: number | null;
  amount_abs?: number | null;
  [key: string]: any;
}
