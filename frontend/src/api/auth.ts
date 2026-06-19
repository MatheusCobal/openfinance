import { apiGet, apiPost } from "./client";

export interface AuthUser {
  id: number;
  email: string;
}

export interface AuthConfig {
  required: boolean;
}

/** Public runtime toggle: keeps local auth-disabled development open. */
export function getAuthConfig() {
  return apiGet<AuthConfig>("/auth/config");
}

/** Current session user. Returns 401 (ApiError) when not authenticated. */
export function getMe() {
  return apiGet<AuthUser>("/auth/me");
}

/** Establish a session. Sets the HttpOnly `of_session` cookie on success. */
export function login(email: string, password: string) {
  return apiPost<AuthUser>("/auth/login", { email, password });
}

/** Revoke the server-side session and clear the cookie. */
export function logout() {
  return apiPost<{ detail: string }>("/auth/logout");
}
