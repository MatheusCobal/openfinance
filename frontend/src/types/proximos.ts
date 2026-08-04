import type { Transaction } from "./common";

interface UpcomingCategory {
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
  detailed_total?: number;
  count: number;
  invoice_total?: number;
  invoice_source?: string;
  invoice_source_label?: string;
  is_current_invoice?: boolean;
  reported_invoice_total?: number | null;
  reported_difference?: number | null;
  cards?: Array<{
    account_id: string;
    account_name?: string | null;
    institution_name?: string | null;
    card_brand?: string | null;
    card_last_four?: string | null;
    pending_total?: number;
    total_amount?: number;
    transaction_count?: number;
    due_date?: string | null;
    closing_day?: number;
    invoice_source?: string;
    is_official?: boolean;
    detailed_total?: number;
    used_credit?: number | null;
    projected_total?: number;
    projected_count?: number;
    credits_total?: number;
    reconciliation_difference?: number;
  }>;
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
