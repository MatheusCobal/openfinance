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
  total: number;
  count: number;
  is_current_invoice?: boolean;
  cards?: Array<{
    account_id: string;
    account_name?: string | null;
    institution_name?: string | null;
    card_brand?: string | null;
    card_last_four?: string | null;
    total_amount: number;
  }>;
  transactions?: Transaction[];
  categories?: UpcomingCategory[];
}

export interface UpcomingSummary {
  months: UpcomingMonth[];
}
