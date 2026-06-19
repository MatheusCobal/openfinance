import { Navigate, Outlet, useLocation } from "react-router-dom";
import { AuthLoading } from "./AuthLoading";
import { useAuth } from "./AuthContext";

/** Route guard for the private app. Waits for the initial /auth/me check, then
 *  renders the app or redirects unauthenticated users to /login (remembering
 *  where they were headed). */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <AuthLoading />;
  if (status === "unauthenticated") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}
