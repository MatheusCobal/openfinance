import { apiGet, apiPost } from "./client";
import type { BankBalanceSummary } from "../types/dashboard";
import type { CreditCardInvoice, PlanningMonth } from "../types/planejamento";
import type { UpcomingSummary } from "../types/proximos";

interface SyncResult {
  failed_accounts: Array<{ account_id: string; error: string }>;
  deleted_transactions: number;
}

export function getPlanningMonth(yearMonth: string) {
  return apiGet<PlanningMonth>(`/planning/month/${yearMonth}`);
}

export function getCurrentInvoice() {
  return apiGet<CreditCardInvoice>("/credit-card/current-invoice");
}

export function getBankBalance() {
  return apiGet<BankBalanceSummary>("/bank/balance-summary");
}

export function getUpcoming() {
  return apiGet<UpcomingSummary>("/upcoming");
}

export function createConnectToken(itemId?: string) {
  return apiPost<{ accessToken: string }>("/connect-token", itemId ? { itemId } : undefined);
}

export function registerPluggyItem(itemId: string) {
  return apiPost(`/items/${encodeURIComponent(itemId)}`);
}

export function syncPluggyItem(itemId: string) {
  return apiPost<SyncResult>(`/items/${encodeURIComponent(itemId)}/sync`);
}
