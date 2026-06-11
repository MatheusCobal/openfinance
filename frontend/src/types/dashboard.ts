import type { CreditCardInvoice, InvoiceCategory, PlanningOverview } from "./planejamento";

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

export interface DashboardCapacity {
  expectedIncome: number;
  fixedCosts: number;
  currentInvoiceAmount: number;
  variableBudget: number;
  variableUsed: number;
  variableRemaining: number;
  availableToSpend: number;
  status: string;
  isFuture: boolean;
}

export interface DashboardData {
  planningMonth: string;
  capacity: PlanningOverview;
  currentInvoice: CreditCardInvoice;
  bankBalance: BankBalanceSummary | null;
  categories: InvoiceCategory[];
}
