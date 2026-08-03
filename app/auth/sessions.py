"""Server-side session storage.

A session is an opaque random token (stored in the ``sessions`` table) mapped to
a user with an expiry. The token is what lives in the client's HttpOnly cookie.

Two read paths exist on purpose:

* ``resolve_current_user`` / ``get_valid_session`` take an *injected* DB session
  and are used by the FastAPI ``get_current_user`` dependency (overridable in
  tests).
* ``session_is_valid`` opens its OWN short-lived session from the module engine
  and is used by the auth middleware, which cannot use FastAPI dependency
  injection. Tests patch this function directly.
"""

import datetime
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session

from app.database import engine
from app.models import AuthSession, User

SESSION_COOKIE_NAME = "of_session"
# Token bytes -> ~43 url-safe chars. Plenty of entropy against guessing.
_TOKEN_BYTES = 32
DEFAULT_SESSION_TTL = datetime.timedelta(days=14)


@dataclass(frozen=True)
class CreatedSession:
    token: str
    expires_at: datetime.datetime


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: Session,
    user_id: int,
    ttl: datetime.timedelta = DEFAULT_SESSION_TTL,
) -> CreatedSession:
    """Create a session while keeping the browser token out of the database."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = _utcnow() + ttl
    row = AuthSession(
        token=_token_digest(token),
        user_id=user_id,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    return CreatedSession(token=token, expires_at=expires_at)


def get_valid_session(db: Session, token: Optional[str]) -> Optional[AuthSession]:
    """Return the session row for ``token`` if present and not expired.

    Expired rows are deleted lazily so the table self-cleans on access.
    """
    if not token:
        return None
    row = db.get(AuthSession, _token_digest(token))
    if row is None:
        # Compatibility window for sessions created before token hashing.
        row = db.get(AuthSession, token)
    if row is None:
        return None
    if row.expires_at <= _utcnow():
        db.delete(row)
        db.commit()
        return None
    return row


def resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    """Return the active ``User`` behind a valid session token, else None."""
    row = get_valid_session(db, token)
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: Session, token: Optional[str]) -> None:
    """Delete the session row for ``token`` if it exists (idempotent)."""
    if not token:
        return
    row = db.get(AuthSession, _token_digest(token)) or db.get(AuthSession, token)
    if row is not None:
        db.delete(row)
        db.commit()


def session_is_valid(token: Optional[str]) -> bool:
    """Middleware gate: True if ``token`` maps to a live session and user.

    Opens its own DB session because middleware runs outside FastAPI dependency
    injection. Tests patch this function to avoid touching the real database.
    """
    if not token:
        return False
    with Session(engine) as db:
        return resolve_current_user(db, token) is not None
