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
  total: number;
  count: number;
  scheduled_total?: number;
  scheduled_count?: number;
  invoice_total?: number;
  invoice_source?: string;
  invoice_source_label?: string;
  is_current_invoice?: boolean;
  transactions?: Transaction[];
  categories?: UpcomingCategory[];
}

export interface UpcomingSummary {
  months: UpcomingMonth[];
  total_count?: number;
  next_invoice?: {
    year_month: string;
    amount: number;
    source_label?: string;
  } | null;
}
