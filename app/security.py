"""Minimal single-user authentication for OpenFinance.

This module adds a thin protection layer so the app can be exposed outside the
local machine with lower risk. It is intentionally simple:

* HTTP Basic Auth (browser-native) for pages and APIs — the browser re-sends the
  credentials automatically on every request, including ``fetch()`` calls from
  the static frontend, so no login screen or frontend change is needed.
* ``/static/*`` is always public (no secrets live there).
* ``/health`` is public when ``OPENFINANCE_PUBLIC_HEALTH`` is true.
* ``/webhooks/pluggy`` is validated by its OWN secret in the query string
  (``?token=...``), never by the admin token — so the admin credential is never
  shared with Pluggy.

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


class SecuritySettings(BaseSettings):
    openfinance_env: str = "local"
    openfinance_require_auth: bool = False
    openfinance_admin_token: str = ""
    openfinance_public_health: bool = True
    openfinance_webhook_secret: str = ""

    model_config = CONFIG_MODEL


def get_security_settings() -> SecuritySettings:
    return SecuritySettings()


def is_static_path(path: str) -> bool:
    return path.startswith(STATIC_PREFIX)


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

    Order of evaluation:
      1. Auth disabled -> pass everything (preserves local dev and existing tests).
      2. ``/static/*`` -> public.
      3. ``/health`` -> public when OPENFINANCE_PUBLIC_HEALTH is true.
      4. ``/webhooks/pluggy`` -> validate its own secret only (never Basic Auth).
      5. Fail-safe: auth required but no admin token -> 500.
      6. Everything else -> require valid Basic Auth.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_security_settings()

        if not settings.openfinance_require_auth:
            return await call_next(request)

        path = request.url.path

        if is_static_path(path):
            return await call_next(request)

        if is_public_health(path, settings):
            return await call_next(request)

        if path == WEBHOOK_PATH:
            token = request.query_params.get("token")
            if verify_webhook_token(token, settings.openfinance_webhook_secret):
                return await call_next(request)
            return _webhook_denied()

        if not settings.openfinance_admin_token:
            return _auth_misconfigured()

        authorization = request.headers.get("Authorization")
        if verify_basic_auth(authorization, settings.openfinance_admin_token):
            return await call_next(request)
        return _basic_auth_challenge()
