import type { ApiErrorShape } from "../types/common";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function normalizeDetail(body: unknown, fallback: string): string {
  const shaped = body as ApiErrorShape | null;
  if (!shaped) return fallback;
  if (Array.isArray(shaped.detail)) {
    return shaped.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  if (typeof shaped.detail === "string") return shaped.detail;
  if (typeof shaped.message === "string") return shaped.message;
  return fallback;
}

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text || null;
}

export async function apiRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(url, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  const body = await parseResponse(response).catch(() => null);
  if (!response.ok) {
    throw new ApiError(normalizeDetail(body, `HTTP ${response.status}`), response.status, body);
  }
  return body as T;
}

export function apiGet<T>(url: string): Promise<T> {
  return apiRequest<T>(url);
}

export function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return apiRequest<T>(url, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiPatch<T>(url: string, body: unknown): Promise<T> {
  return apiRequest<T>(url, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function apiPut<T>(url: string, body: unknown): Promise<T> {
  return apiRequest<T>(url, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function apiDelete<T = null>(url: string): Promise<T> {
  return apiRequest<T>(url, { method: "DELETE" });
}
