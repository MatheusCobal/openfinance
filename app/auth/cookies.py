"""Session cookie helpers.

The cookie is always ``HttpOnly`` + ``SameSite=Lax``. The ``Secure`` flag is
driven by the environment (production), NOT by the request scheme: the app runs
behind Caddy over plain HTTP on the internal network, so ``request.url.scheme``
is ``http`` and could not be trusted to decide ``Secure``.
"""

from starlette.responses import Response

from app.auth.sessions import DEFAULT_SESSION_TTL, SESSION_COOKIE_NAME
from app.security import is_production

_MAX_AGE = int(DEFAULT_SESSION_TTL.total_seconds())


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=is_production(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_production(),
    )
