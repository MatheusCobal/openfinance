"""FastAPI auth dependencies.

``get_current_user`` is the seam for future per-user data isolation: today it
gates a handler and returns the authenticated ``User``; later, handlers will use
``current_user.id`` to filter financial queries (see the auth plan, "Fase 6").
"""

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

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
