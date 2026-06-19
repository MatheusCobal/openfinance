"""Authentication endpoints: login, logout, current user.

Session model: own login validated against the ``users`` table (Argon2id),
server-side opaque session stored in the ``sessions`` table, carried in an
HttpOnly cookie. No JWT, no Basic Auth, no public signup.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.cookies import clear_session_cookie, set_session_cookie
from app.auth.dependencies import get_current_user
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import SESSION_COOKIE_NAME, create_session, revoke_session
from app.database import get_session
from app.models import User
from app import security

router = APIRouter(prefix="/auth", tags=["auth"])

# A throwaway Argon2id hash. Verifying against it when the email is unknown keeps
# login timing roughly constant, so responses don't reveal which emails exist.
_DUMMY_HASH = hash_password("openfinance-dummy-password")


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str


class AuthConfigOut(BaseModel):
    required: bool


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.get("/config", response_model=AuthConfigOut)
def config(response: Response) -> AuthConfigOut:
    """Return the public auth toggle used to bootstrap the React route guard."""
    response.headers["Cache-Control"] = "no-store"
    return AuthConfigOut(required=security.get_security_settings().openfinance_require_auth)


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_session)) -> User:
    email = _normalize_email(body.email)
    user = db.exec(select(User).where(User.email == email)).first()

    # Always run a verify (real or dummy) so the response time does not leak
    # whether the email exists.
    password_hash = user.password_hash if user is not None else _DUMMY_HASH
    password_ok = verify_password(body.password, password_hash)

    if user is None or not user.is_active or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    session_row = create_session(db, user.id)
    set_session_cookie(response, session_row.token)
    return user


@router.get("/me", response_model=UserOut)
def me(response: Response, current_user: User = Depends(get_current_user)) -> User:
    response.headers["Cache-Control"] = "no-store"
    return current_user


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_session)) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    revoke_session(db, token)
    clear_session_cookie(response)
    return {"detail": "Logged out."}
