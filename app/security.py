"""Authentication gate for OpenFinance.

The app authenticates users with their own login (see ``app/routes/auth.py``):
a server-side opaque session token is stored in the ``sessions`` table and
carried in an HttpOnly cookie. This middleware is the coarse gate that blocks
unauthenticated access to the whole app; handlers that need the user object use
the ``get_current_user`` dependency.

Public surface (even with auth enabled):

* ``/static/*`` — bundled assets, no secrets.
* ``/`` and ``/login`` — institutional landing and the login page (no data).
* ``/auth/login`` — the endpoint that establishes a session.
* ``/auth/config`` — exposes only whether login is required, so the React app
  can preserve auth-disabled local development.
* ``/health`` — public when ``OPENFINANCE_PUBLIC_HEALTH`` is true.
* ``/webhooks/pluggy`` — validated by its OWN secret in the query string
  (``?token=...``), independently of the user-auth toggle.

Security settings are read PER REQUEST through ``get_security_settings`` so tests
can patch the function directly, avoiding global-state ordering problems. When
``OPENFINANCE_REQUIRE_AUTH`` is false (default) the gate is a no-op, keeping
local development and the test suite unaffected.
"""

import secrets
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth import sessions as auth_sessions

CONFIG_MODEL = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)

WEBHOOK_PATH = "/webhooks/pluggy"
STATIC_PREFIX = "/static/"
HEALTH_PATH = "/health"
LOGIN_PATH = "/login"
# Pages that stay public even with auth enabled. Keep this minimal: only static
# pages with zero financial data (landing) and the login page. The logged-in app
# (/dashboard and friends) must NEVER be added.
PUBLIC_PAGE_PATHS = frozenset({"/", LOGIN_PATH})
# Auth endpoints reachable without a session: one establishes it and the other
# exposes only the public auth toggle needed to bootstrap the React app.
PUBLIC_AUTH_PATHS = frozenset({"/auth/login", "/auth/config"})


class SecuritySettings(BaseSettings):
    openfinance_env: str = "local"
    openfinance_require_auth: bool = False
    openfinance_public_health: bool = True
    openfinance_webhook_secret: str = ""

    model_config = CONFIG_MODEL


class SecurityConfigurationError(RuntimeError):
    """Raised when the security configuration is unsafe to start the application."""


def get_security_settings() -> SecuritySettings:
    return SecuritySettings()


def _is_production(env: str) -> bool:
    return env.strip().lower() == "production"


def is_production() -> bool:
    """True when the running environment is production (drives the Secure cookie)."""
    return _is_production(get_security_settings().openfinance_env)


def validate_security_configuration(settings: SecuritySettings) -> None:
    """Raise SecurityConfigurationError if the configuration is unsafe.

    In production the user-auth gate must be enabled; otherwise the app would be
    exposed without authentication. The first user is created out of band (see
    ``scripts/create_user.py``), so no token needs to be present to start.

    The webhook secret is NOT required to start: a missing secret means the
    webhook path rejects all calls, which is safe.
    """
    if _is_production(settings.openfinance_env) and not settings.openfinance_require_auth:
        raise SecurityConfigurationError(
            "OPENFINANCE_REQUIRE_AUTH must be true when OPENFINANCE_ENV=production."
        )


def is_static_path(path: str) -> bool:
    return path.startswith(STATIC_PREFIX)


def is_public_page(path: str) -> bool:
    return path in PUBLIC_PAGE_PATHS


def is_public_auth_path(path: str) -> bool:
    return path in PUBLIC_AUTH_PATHS


def is_public_health(path: str, settings: SecuritySettings) -> bool:
    return path == HEALTH_PATH and settings.openfinance_public_health


def verify_webhook_token(token: Optional[str], webhook_secret: str) -> bool:
    """Validate a webhook query token against the configured secret (constant-time).

    Returns False if the secret is unset or the token is missing/incorrect, so a
    misconfigured deployment rejects webhooks instead of accepting them blindly.
    """
    if not webhook_secret:
        return False
    if not token:
        return False
    return secrets.compare_digest(token, webhook_secret)


def _auth_challenge(request: Request) -> Response:
    """Reject an unauthenticated request.

    Browser navigations (Accept: text/html) are redirected to the login page;
    API/fetch calls get a 401 JSON so the frontend can react programmatically.
    """
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(url=LOGIN_PATH, status_code=303)
    return JSONResponse({"detail": "Authentication required."}, status_code=401)


def _webhook_denied() -> Response:
    return JSONResponse(
        {"detail": "Invalid or missing webhook token."},
        status_code=403,
    )


class OpenFinanceAuthMiddleware(BaseHTTPMiddleware):
    """Gate requests according to the security settings.

    Dispatch order:
      1. Webhook path: handled independently of the user-auth toggle.
         - Secret configured: always require the correct token (even in
           local/dev mode) so the route is never open while a secret is set.
         - No secret + require_auth=false: pass through (local dev).
         - No secret + require_auth=true: deny (misconfigured).
      2. Auth disabled → pass everything else (local dev / test suite).
      3. ``/static/*`` and public pages (``/``, ``/login``) → public.
      4. ``/auth/login`` and ``/auth/config`` → public (session bootstrap).
      5. ``/health`` → public when OPENFINANCE_PUBLIC_HEALTH is true.
      6. Everything else → require a valid session cookie.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_security_settings()
        path = request.url.path

        # Step 1: webhook path is evaluated first, independently of require_auth.
        if path == WEBHOOK_PATH:
            if settings.openfinance_webhook_secret:
                token = request.query_params.get("token")
                if verify_webhook_token(token, settings.openfinance_webhook_secret):
                    return await call_next(request)
                return _webhook_denied()
            if not settings.openfinance_require_auth:
                return await call_next(request)
            return _webhook_denied()

        # Step 2: auth disabled → open to everything.
        if not settings.openfinance_require_auth:
            return await call_next(request)

        # Steps 3-5: public surface.
        if is_static_path(path) or is_public_page(path):
            return await call_next(request)
        if is_public_auth_path(path):
            return await call_next(request)
        if is_public_health(path, settings):
            return await call_next(request)

        # Step 6: require a valid session cookie.
        token = request.cookies.get(auth_sessions.SESSION_COOKIE_NAME)
        if auth_sessions.session_is_valid(token):
            return await call_next(request)
        return _auth_challenge(request)
