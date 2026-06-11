"""Minimal single-user authentication for OpenFinance.

This module adds a thin protection layer so the app can be exposed outside the
local machine with lower risk. It is intentionally simple:

* HTTP Basic Auth (browser-native) for pages and APIs — the browser re-sends the
  credentials automatically on every request, including ``fetch()`` calls from
  the static frontend, so no login screen or frontend change is needed.
* ``/static/*`` is always public (no secrets live there).
* ``/`` (institutional landing page) is always public — it is a static
  marketing page with simulated data only, no financial information.
* ``/health`` is public when ``OPENFINANCE_PUBLIC_HEALTH`` is true.
* ``/webhooks/pluggy`` is validated by its OWN secret in the query string
  (``?token=...``).  Once a webhook secret is configured it is enforced
  regardless of ``OPENFINANCE_REQUIRE_AUTH``, so the route is never open while
  a secret exists — even in local/dev mode.

Security settings are read PER REQUEST through ``get_security_settings`` so tests
can patch the function directly, avoiding global-state ordering problems.

Username is ignored in Basic Auth: any username is accepted and only the
password is validated against ``OPENFINANCE_ADMIN_TOKEN`` (constant-time). This
keeps usage simple — the user types any name and the token as the password.
"""

import base64
import binascii
import secrets
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CONFIG_MODEL = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)

WEBHOOK_PATH = "/webhooks/pluggy"
STATIC_PREFIX = "/static/"
HEALTH_PATH = "/health"
# Pages that stay public even with auth enabled. Keep this list minimal and
# explicit: only static institutional pages with zero financial data belong
# here. The logged-in app (/dashboard and friends) must NEVER be added.
PUBLIC_PAGE_PATHS = frozenset({"/"})


class SecuritySettings(BaseSettings):
    openfinance_env: str = "local"
    openfinance_require_auth: bool = False
    openfinance_admin_token: str = ""
    openfinance_public_health: bool = True
    openfinance_webhook_secret: str = ""

    model_config = CONFIG_MODEL


class SecurityConfigurationError(RuntimeError):
    """Raised when the security configuration is unsafe to start the application."""


def get_security_settings() -> SecuritySettings:
    return SecuritySettings()


def _is_production(env: str) -> bool:
    return env.strip().lower() == "production"


def validate_security_configuration(settings: SecuritySettings) -> None:
    """Raise SecurityConfigurationError if the configuration is unsafe.

    Conditions checked (in order):
    1. production + require_auth=false  → unsafe: auth must be enabled.
    2. production + empty admin token   → unsafe: token must be set.
    3. require_auth=true + empty token  → unsafe: token must be set (any env).

    Webhook secret is NOT required to start: a missing secret means the webhook
    path rejects all calls, which is safe — the route simply won't accept Pluggy
    callbacks until the secret is configured.
    """
    is_prod = _is_production(settings.openfinance_env)

    if is_prod and not settings.openfinance_require_auth:
        raise SecurityConfigurationError(
            "OPENFINANCE_REQUIRE_AUTH must be true when OPENFINANCE_ENV=production."
        )
    if is_prod and not settings.openfinance_admin_token:
        raise SecurityConfigurationError(
            "OPENFINANCE_ADMIN_TOKEN must be set when OPENFINANCE_ENV=production."
        )
    if settings.openfinance_require_auth and not settings.openfinance_admin_token:
        raise SecurityConfigurationError(
            "OPENFINANCE_ADMIN_TOKEN must be set when authentication is required."
        )


def is_static_path(path: str) -> bool:
    return path.startswith(STATIC_PREFIX)


def is_public_page(path: str) -> bool:
    return path in PUBLIC_PAGE_PATHS


def is_public_health(path: str, settings: SecuritySettings) -> bool:
    return path == HEALTH_PATH and settings.openfinance_public_health


def verify_basic_auth(header: Optional[str], admin_token: str) -> bool:
    """Validate an ``Authorization: Basic`` header against the admin token.

    The username is ignored; only the password is checked (constant-time).
    Returns False for any malformed header or empty admin token.
    """
    if not admin_token:
        return False
    if not header or not header.startswith("Basic "):
        return False
    encoded = header[len("Basic ") :].strip()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    # "username:password" — split on the first colon, password may contain colons.
    _, sep, password = decoded.partition(":")
    if not sep:
        return False
    return secrets.compare_digest(password, admin_token)


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


def _basic_auth_challenge() -> Response:
    return JSONResponse(
        {"detail": "Authentication required."},
        status_code=401,
        headers={"WWW-Authenticate": "Basic"},
    )


def _webhook_denied() -> Response:
    return JSONResponse(
        {"detail": "Invalid or missing webhook token."},
        status_code=403,
    )


def _auth_misconfigured() -> Response:
    # Names only — never echo the secret value.
    return JSONResponse(
        {"detail": "Server auth misconfigured: OPENFINANCE_ADMIN_TOKEN is not set."},
        status_code=500,
    )


class OpenFinanceAuthMiddleware(BaseHTTPMiddleware):
    """Gate requests according to the security settings.

    Dispatch order:
      1. Webhook path: handled independently of the global auth toggle.
         - If a webhook secret is configured: always require the correct token
           (even in local/dev mode with require_auth=false) so the route is
           never open while a secret is set.
         - If no secret is set and require_auth=false: pass through (local dev).
         - If no secret is set and require_auth=true: deny (misconfigured).
      2. Auth disabled → pass everything else (local dev / test suite).
      3. ``/static/*`` and public pages (``/``) → public.
      4. ``/health`` → public when OPENFINANCE_PUBLIC_HEALTH is true.
      5. Fail-safe: auth required but no admin token → 500.
      6. Everything else → require valid Basic Auth.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_security_settings()
        path = request.url.path

        # Step 1: webhook path is evaluated first, independently of require_auth.
        if path == WEBHOOK_PATH:
            if settings.openfinance_webhook_secret:
                # Secret is configured: always validate the token regardless of
                # the global auth toggle.
                token = request.query_params.get("token")
                if verify_webhook_token(token, settings.openfinance_webhook_secret):
                    return await call_next(request)
                return _webhook_denied()
            # No secret configured.
            if not settings.openfinance_require_auth:
                # Local/dev mode with no secret: pass through for easy development.
                return await call_next(request)
            # Auth is required but no secret is set: deny the webhook.
            return _webhook_denied()

        # Step 2: auth disabled → open to everything.
        if not settings.openfinance_require_auth:
            return await call_next(request)

        # Steps 3-6: auth is required.
        if is_static_path(path):
            return await call_next(request)

        if is_public_page(path):
            return await call_next(request)

        if is_public_health(path, settings):
            return await call_next(request)

        if not settings.openfinance_admin_token:
            return _auth_misconfigured()

        authorization = request.headers.get("Authorization")
        if verify_basic_auth(authorization, settings.openfinance_admin_token):
            return await call_next(request)
        return _basic_auth_challenge()
