"""FastAPI auth dependencies.

``get_current_user`` gates a handler and returns the authenticated ``User``.
``current_scope_user_id`` is the seam for per-user data isolation (Fase 6):
handlers pass its result into the service layer to filter financial queries.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app import security
from app.auth.sessions import SESSION_COOKIE_NAME, resolve_current_user
from app.database import get_session
from app.models import User


def get_current_user(
    request: Request,
    db: Session = Depends(get_session),
) -> User:
    """Return the authenticated user or raise 401.

    Reads the opaque session token from the HttpOnly cookie and resolves it
    against the ``sessions`` table.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_current_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def current_scope_user_id(
    request: Request,
    db: Session = Depends(get_session),
) -> Optional[int]:
    """The user id financial queries should be scoped to.

    Returns ``None`` when auth is disabled (local/open mode and the test suite
    run a single shared dataset, so no isolation filter is applied). When auth
    is enabled the middleware has already guaranteed a valid session, so we
    resolve it to the owning user's id; we still fail closed with 401 if the
    session cannot be resolved here.
    """
    if not security.get_security_settings().openfinance_require_auth:
        return None
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_current_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user.id
