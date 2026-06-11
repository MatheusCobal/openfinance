import { apiGet, apiPost } from "./client";
import type { BankBalanceSummary } from "../types/dashboard";
import type { CreditCardInvoice, PlanningMonth } from "../types/planejamento";

export function getPlanningMonth(yearMonth: string) {
  return apiGet<PlanningMonth>(`/planning/month/${yearMonth}`);
}

export function getCurrentInvoice() {
  return apiGet<CreditCardInvoice>("/credit-card/current-invoice");
}

export function getBankBalance() {
  return apiGet<BankBalanceSummary>("/bank/balance-summary");
}

export function createConnectToken(itemId?: string) {
  return apiPost<{ accessToken: string }>("/connect-token", itemId ? { itemId } : undefined);
}

export function registerPluggyItem(itemId: string) {
  return apiPost(`/items/${encodeURIComponent(itemId)}`);
}

export function syncPluggyItem(itemId: string) {
  return apiPost(`/items/${encodeURIComponent(itemId)}/sync`);
}
