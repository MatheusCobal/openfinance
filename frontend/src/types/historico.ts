import type { Transaction } from "./common";

interface InvoiceHistoryCategory {
  id: string;
  name: string;
  total: number;
  count: number;
  transactions?: Transaction[];
  months?: Array<{ month: string; total: number; count: number; transactions?: Transaction[] }>;
  average_monthly?: number;
  average_12m?: number;
  average_months_used?: number;
  difference_from_average?: number;
  difference_percent?: number;
}

export interface InvoiceHistoryCard {
  account_id: string;
  account_name?: string | null;
  institution_name?: string | null;
  card_brand?: string | null;
  card_last_four?: string | null;
  total: number;
  count?: number;
  source?: string;
}

export interface InvoiceHistoryMonth {
  month: string;
  total: number;
  count: number;
  invoice_display_total?: number;
  classified_purchase_total?: number;
  invoice_total_source?: string;
  cards?: InvoiceHistoryCard[];
  card_breakdown_total?: number;
  card_breakdown_source?: string;
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

interface CashflowMonth {
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
