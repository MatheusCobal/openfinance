"""Tests for own-login authentication (Fase 2).

Covers password hashing, the server-side session store, the /auth endpoints and
the session-cookie gate in OpenFinanceAuthMiddleware.
"""

import datetime
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.security as security
from app.auth import sessions as auth_sessions
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import (
    SESSION_COOKIE_NAME,
    create_session,
    get_valid_session,
    resolve_current_user,
    revoke_session,
)
from app.database import get_session
from app.main import app
from app.models import AuthSession, User


def make_settings(*, require_auth=False, public_health=True, webhook_secret="", env="local"):
    return security.SecuritySettings(
        _env_file=None,
        openfinance_env=env,
        openfinance_require_auth=require_auth,
        openfinance_public_health=public_health,
        openfinance_webhook_secret=webhook_secret,
    )


def make_memory_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class PasswordTest(unittest.TestCase):
    def test_hash_is_not_plaintext_and_is_argon2id(self):
        hashed = hash_password("correct horse")
        self.assertNotEqual(hashed, "correct horse")
        self.assertTrue(hashed.startswith("$argon2id$"))

    def test_verify_accepts_correct_and_rejects_wrong(self):
        hashed = hash_password("s3cret")
        self.assertTrue(verify_password("s3cret", hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_verify_never_raises_on_malformed_hash(self):
        self.assertFalse(verify_password("anything", "not-a-valid-hash"))


class AuthSchemaScopeTest(unittest.TestCase):
    def test_user_id_exists_only_on_the_auth_session_table(self):
        tables_with_user_id = {
            table.name for table in SQLModel.metadata.tables.values() if "user_id" in table.c
        }
        self.assertEqual(tables_with_user_id, {"sessions"})


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_memory_engine()
        with Session(self.engine) as db:
            user = User(email="a@b.com", password_hash=hash_password("pw"))
            db.add(user)
            db.commit()
            db.refresh(user)
            self.user_id = user.id

    def test_create_and_resolve(self):
        with Session(self.engine) as db:
            row = create_session(db, self.user_id)
            self.assertTrue(row.token)
            self.assertGreater(row.expires_at, datetime.datetime.utcnow())
            user = resolve_current_user(db, row.token)
            self.assertIsNotNone(user)
            self.assertEqual(user.id, self.user_id)

    def test_expired_session_is_rejected_and_deleted(self):
        with Session(self.engine) as db:
            row = create_session(db, self.user_id, ttl=datetime.timedelta(seconds=-1))
            token = row.token
            self.assertIsNone(get_valid_session(db, token))
            self.assertIsNone(db.get(AuthSession, token))

    def test_revoke_removes_session(self):
        with Session(self.engine) as db:
            row = create_session(db, self.user_id)
            revoke_session(db, row.token)
            self.assertIsNone(get_valid_session(db, row.token))

    def test_resolve_inactive_user_returns_none(self):
        with Session(self.engine) as db:
            row = create_session(db, self.user_id)
            user = db.get(User, self.user_id)
            user.is_active = False
            db.add(user)
            db.commit()
            self.assertIsNone(resolve_current_user(db, row.token))

    def test_missing_token_returns_none(self):
        with Session(self.engine) as db:
            self.assertIsNone(get_valid_session(db, None))
            self.assertIsNone(resolve_current_user(db, ""))


class AuthFlowTest(unittest.TestCase):
    """End-to-end login/me/logout with auth open at the gate (local mode)."""

    def setUp(self):
        self.engine = make_memory_engine()
        with Session(self.engine) as db:
            db.add(User(email="user@example.com", password_hash=hash_password("hunter2")))
            db.add(
                User(
                    email="inactive@example.com",
                    password_hash=hash_password("hunter2"),
                    is_active=False,
                )
            )
            db.commit()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self._settings_patch = patch.object(
            security, "get_security_settings", lambda: make_settings(env="local")
        )
        self._settings_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._settings_patch.stop()
        app.dependency_overrides.clear()

    def test_login_sets_httponly_lax_insecure_cookie_in_local(self):
        response = self.client.post(
            "/auth/login", json={"email": "user@example.com", "password": "hunter2"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "user@example.com")
        set_cookie = response.headers["set-cookie"].lower()
        self.assertIn(f"{SESSION_COOKIE_NAME}=", set_cookie)
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)
        self.assertNotIn("secure", set_cookie)

    def test_login_normalizes_email_case(self):
        response = self.client.post(
            "/auth/login", json={"email": "USER@example.com ", "password": "hunter2"}
        )
        self.assertEqual(response.status_code, 200)

    def test_login_wrong_password_401(self):
        response = self.client.post(
            "/auth/login", json={"email": "user@example.com", "password": "nope"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")

    def test_login_unknown_email_401(self):
        response = self.client.post(
            "/auth/login", json={"email": "ghost@example.com", "password": "hunter2"}
        )
        self.assertEqual(response.status_code, 401)

    def test_login_inactive_user_401(self):
        response = self.client.post(
            "/auth/login", json={"email": "inactive@example.com", "password": "hunter2"}
        )
        self.assertEqual(response.status_code, 401)

    def test_me_requires_session(self):
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_config_reports_auth_disabled(self):
        response = self.client.get("/auth/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"required": False})
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_full_flow_login_me_logout(self):
        login = self.client.post(
            "/auth/login", json={"email": "user@example.com", "password": "hunter2"}
        )
        self.assertEqual(login.status_code, 200)

        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "user@example.com")
        self.assertEqual(me.headers["cache-control"], "no-store")

        logout = self.client.post("/auth/logout")
        self.assertEqual(logout.status_code, 200)

        after = self.client.get("/auth/me")
        self.assertEqual(after.status_code, 401)

    def test_login_secure_cookie_in_production(self):
        with patch.object(
            security, "get_security_settings", lambda: make_settings(env="production")
        ):
            response = self.client.post(
                "/auth/login", json={"email": "user@example.com", "password": "hunter2"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("secure", response.headers["set-cookie"].lower())


class AuthGateTest(unittest.TestCase):
    """Middleware behavior when require_auth=true (session_is_valid is patched)."""

    def setUp(self):
        self.engine = make_memory_engine()

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _use(self, **kwargs):
        settings = make_settings(require_auth=True, **kwargs)
        return patch.object(security, "get_security_settings", lambda: settings)

    def test_html_request_without_session_redirects_to_login(self):
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.get("/dashboard", headers={"accept": "text/html"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_api_request_without_session_returns_401(self):
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.get("/planning/month/2026-07")
        self.assertEqual(response.status_code, 401)

    def test_valid_session_cookie_passes(self):
        self.client.cookies.set(SESSION_COOKIE_NAME, "good")
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: True):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    def test_login_endpoint_is_public(self):
        # Reaches the route (returns the route's 401, not the gate's) without a session.
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.post(
                "/auth/login", json={"email": "nobody@example.com", "password": "x"}
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")

    def test_config_endpoint_is_public_and_reports_auth_required(self):
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.get("/auth/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"required": True})

    def test_login_page_is_not_gated(self):
        # /login must be public, otherwise an HTML request would redirect to
        # itself forever.
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.get("/login", headers={"accept": "text/html"})
        self.assertEqual(response.status_code, 200)

    def test_static_stays_public(self):
        with self._use(), patch.object(auth_sessions, "session_is_valid", lambda token: False):
            response = self.client.get("/static/landing.js")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
