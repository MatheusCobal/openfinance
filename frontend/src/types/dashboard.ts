export interface BankBalanceSummary {
  total: number;
  account_count: number;
  accounts: Array<{
    id: string;
    name: string;
    type: string;
    balance?: number | null;
    balance_updated_at?: string | null;
  }>;
  source: string;
}
