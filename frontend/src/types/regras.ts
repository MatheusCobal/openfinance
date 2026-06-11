export interface ClassificationRule {
  id: number;
  name: string;
  enabled: boolean;
  priority: number;
  account_type_scope: "ALL" | "CREDIT" | "BANK" | string;
  match_pluggy_category?: string | null;
  match_pluggy_subcategory?: string | null;
  match_pluggy_type?: string | null;
  match_merchant?: string | null;
  match_description?: string | null;
  match_amount_sign?: "any" | "positive" | "negative" | string;
  target_internal_category: string;
  target_cashflow_type: string;
  ignored_from_totals?: boolean | null;
  affected_count?: number;
}

export type ClassificationRulePayload = Omit<ClassificationRule, "id" | "affected_count">;

export interface ClassificationPreviewExample {
  description?: string;
  date?: string;
  account_type?: string;
  amount?: number;
  pluggy_raw_category?: string | null;
  pluggy_raw_subcategory?: string | null;
  pluggy_raw_type?: string | null;
  pluggy_merchant?: string | null;
  current_internal_category?: string | null;
  current_cashflow_type?: string | null;
  new_internal_category?: string | null;
  new_cashflow_type?: string | null;
}

export interface ClassificationPreview {
  matched_count: number;
  examples?: ClassificationPreviewExample[];
}
