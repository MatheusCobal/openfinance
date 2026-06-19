import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  getAuthConfig,
  getMe,
  login as apiLogin,
  logout as apiLogout,
  type AuthUser,
} from "../api/auth";
import { setUnauthorizedHandler } from "../api/client";

type AuthStatus = "loading" | "disabled" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  authRequired: boolean;
  /** Throws ApiError(401) on invalid credentials so the form can show a message. */
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [authRequired, setAuthRequired] = useState(true);

  // Read the runtime toggle first so auth-disabled local development remains
  // open. When auth is enabled, restore the session by asking who we are.
  useEffect(() => {
    let active = true;
    getAuthConfig()
      .then(async ({ required }) => {
        if (!active) return;
        setAuthRequired(required);
        if (!required) {
          setStatus("disabled");
          return;
        }

        try {
          const u = await getMe();
          if (!active) return;
          setUser(u);
          setStatus("authenticated");
        } catch {
          if (!active) return;
          setUser(null);
          setStatus("unauthenticated");
        }
      })
      .catch(() => {
        if (!active) return;
        // Fail closed if the runtime auth configuration cannot be loaded.
        setAuthRequired(true);
        setUser(null);
        setStatus("unauthenticated");
      });
    return () => {
      active = false;
    };
  }, []);

  // When any non-auth API call returns 401 (e.g. the session expired), drop to
  // unauthenticated so RequireAuth redirects to /login.
  useEffect(() => {
    setUnauthorizedHandler(
      authRequired
        ? () => {
            setUser(null);
            setStatus("unauthenticated");
          }
        : null,
    );
    return () => setUnauthorizedHandler(null);
  }, [authRequired]);

  const login = useCallback(async (email: string, password: string) => {
    const u = await apiLogin(email, password);
    setUser(u);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, authRequired, login, logout }),
    [user, status, authRequired, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
