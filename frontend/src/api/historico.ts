import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type { ClassificationOptions } from "../types/common";
import type { CashflowRule, CashflowSummary, InvoiceHistorySummary } from "../types/historico";

export function getInvoiceHistory(months = 12) {
  return apiGet<InvoiceHistorySummary>(`/credit-card-invoices/monthly?months=${months}`);
}

export function getCashflow(months = 12) {
  return apiGet<CashflowSummary>(`/bank-cashflow/monthly?months=${months}`);
}

export function listCashflowRules() {
  return apiGet<CashflowRule[]>("/bank-cashflow/exclusion-rules");
}

export function createCashflowRule(body: {
  direction: string;
  pluggy_category?: string;
  pattern?: string;
}) {
  return apiPost<CashflowRule>("/bank-cashflow/exclusion-rules", body);
}

export function deleteCashflowRule(id: number) {
  return apiDelete(`/bank-cashflow/exclusion-rules/${id}`);
}

export function getClassificationOptions() {
  return apiGet<ClassificationOptions>("/transactions/classification-options");
}

export function updateTransactionClassification(
  transactionId: string,
  body: {
    internal_category: string;
    cashflow_type: string;
    ignored_from_totals?: boolean | null;
  },
) {
  return apiPatch(`/transactions/${encodeURIComponent(transactionId)}/classification`, body);
}

export function resetTransactionClassification(transactionId: string) {
  return apiDelete(`/transactions/${encodeURIComponent(transactionId)}/classification-override`);
}
