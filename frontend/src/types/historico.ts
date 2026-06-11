import type { Transaction } from "./common";

export interface InvoiceHistoryCategory {
  id: string;
  name: string;
  total: number;
  count: number;
  transactions?: Transaction[];
  average_12m?: number;
  average_months_used?: number;
  difference_from_average?: number;
  difference_percent?: number;
}

export interface InvoiceHistoryMonth {
  month: string;
  total: number;
  count: number;
  invoice_display_total?: number;
  classified_purchase_total?: number;
  invoice_total_source?: string;
  categories?: InvoiceHistoryCategory[];
  transactions?: Transaction[];
}

export interface InvoiceHistorySummary {
  months: InvoiceHistoryMonth[];
  total?: number;
  total_count?: number;
  invoice_display_total?: number;
  classified_purchase_total?: number;
}

export interface CashflowMonth {
  month: string;
  income?: number;
  outflow?: number;
  net?: number;
  income_count?: number;
  outflow_count?: number;
  transactions?: Transaction[];
}

export interface CashflowSummary {
  summary?: {
    income?: number;
    outflow?: number;
    net?: number;
  };
  months: CashflowMonth[];
}

export interface CashflowRule {
  id: number;
  direction?: string;
  pluggy_category?: string | null;
  pattern?: string | null;
  affected_count?: number;
}
