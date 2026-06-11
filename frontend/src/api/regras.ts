import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type { ClassificationOptions } from "../types/common";
import type {
  ClassificationPreview,
  ClassificationRule,
  ClassificationRulePayload,
} from "../types/regras";

const RULES_URL = "/transactions/classification-rules";

export function getClassificationOptions() {
  return apiGet<ClassificationOptions>("/transactions/classification-options");
}

export function listClassificationRules() {
  return apiGet<ClassificationRule[]>(RULES_URL);
}

export function createClassificationRule(body: ClassificationRulePayload) {
  return apiPost<ClassificationRule>(RULES_URL, body);
}

export function updateClassificationRule(id: number, body: Partial<ClassificationRulePayload>) {
  return apiPatch<ClassificationRule>(`${RULES_URL}/${id}`, body);
}

export function deleteClassificationRule(id: number) {
  return apiDelete(`${RULES_URL}/${id}`);
}

export function previewNewRule(body: ClassificationRulePayload) {
  return apiPost<ClassificationPreview>(`${RULES_URL}/preview`, body);
}

export function previewExistingRule(id: number, body: Partial<ClassificationRulePayload> = {}) {
  return apiPost<ClassificationPreview>(`${RULES_URL}/${id}/preview`, body);
}
