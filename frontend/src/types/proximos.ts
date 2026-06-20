import type { Transaction } from "./common";

export interface UpcomingCategory {
  id?: string | number;
  name?: string;
  total: number;
  count: number;
  transactions?: Transaction[];
}

export interface UpcomingMonth {
  month: string;
  transaction_month: string;
  total: number;
  count: number;
  invoice_total?: number;
  invoice_source?: string;
  invoice_source_label?: string;
  is_current_invoice?: boolean;
  reported_invoice_total?: number | null;
  reported_difference?: number | null;
  transactions?: Transaction[];
  categories?: UpcomingCategory[];
}

export interface UpcomingSummary {
  months: UpcomingMonth[];
  total_count?: number;
  next_invoice?: {
    year_month: string;
    transaction_month: string;
    amount: number;
    reported_amount?: number;
    source?: string;
    source_label?: string;
  } | null;
}
