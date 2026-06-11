import { apiGet } from "./client";
import type { UpcomingSummary } from "../types/proximos";

export function getUpcoming() {
  return apiGet<UpcomingSummary>("/upcoming");
}
