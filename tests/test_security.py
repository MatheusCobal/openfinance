"""Tests for the session-cookie auth gate and security configuration.

The middleware reads security settings per request via
``app.security.get_security_settings`` and validates sessions via
``app.auth.sessions.session_is_valid``; tests patch both to control auth state
deterministically — no environment ordering, no real database, no secrets.
"""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.security as security
from app.auth import sessions as auth_sessions
from app.auth.sessions import SESSION_COOKIE_NAME
from app.database import get_session
from app.main import app

WEBHOOK_SECRET = "test-webhook-secret-xyz"


def make_settings(
    *,
    require_auth=False,
    public_health=True,
    webhook_secret="",
    env="local",
):
    return security.SecuritySettings(
        _env_file=None,
        openfinance_env=env,
        openfinance_require_auth=require_auth,
        openfinance_public_health=public_health,
        openfinance_webhook_secret=webhook_secret,
    )


class ConfigValidationTest(unittest.TestCase):
    def test_production_without_auth_raises(self):
        settings = make_settings(env="production", require_auth=False)
        with self.assertRaises(security.SecurityConfigurationError) as ctx:
            security.validate_security_configuration(settings)
        self.assertIn("OPENFINANCE_REQUIRE_AUTH", str(ctx.exception))

    def test_production_with_auth_passes(self):
        # No admin token required to start: the first user is created out of band.
        settings = make_settings(env="production", require_auth=True)
        security.validate_security_configuration(settings)  # must not raise

    def test_local_default_passes(self):
        settings = make_settings(env="local", require_auth=False)
        security.validate_security_configuration(settings)  # must not raise

    def test_production_env_case_insensitive(self):
        for env_value in ("Production", " production ", "PRODUCTION", " Production "):
            with self.subTest(env=env_value):
                settings = make_settings(env=env_value, require_auth=False)
                with self.assertRaises(security.SecurityConfigurationError):
                    security.validate_security_configuration(settings)


class SecuritySettingsTest(unittest.TestCase):
    def test_defaults_are_local_and_open(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        self.assertEqual(settings.openfinance_env, "local")
        self.assertFalse(settings.openfinance_require_auth)
        self.assertTrue(settings.openfinance_public_health)
        self.assertEqual(settings.openfinance_webhook_secret, "")

    def test_bool_parsed_from_env(self):
        with patch.dict(os.environ, {"OPENFINANCE_REQUIRE_AUTH": "true"}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        self.assertTrue(settings.openfinance_require_auth)

    def test_admin_token_field_was_removed(self):
        # The shared-token Basic Auth gate is gone; no admin token field remains.
        with patch.dict(os.environ, {}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        self.assertFalse(hasattr(settings, "openfinance_admin_token"))


class IsProductionTest(unittest.TestCase):
    def test_is_production_reads_settings(self):
        with patch.object(security, "get_security_settings", lambda: make_settings(env="production")):
            self.assertTrue(security.is_production())
        with patch.object(security, "get_security_settings", lambda: make_settings(env="local")):
            self.assertFalse(security.is_production())


class WebhookHelperTest(unittest.TestCase):
    def test_verify_webhook_token(self):
        self.assertTrue(security.verify_webhook_token(WEBHOOK_SECRET, WEBHOOK_SECRET))
        self.assertFalse(security.verify_webhook_token("wrong", WEBHOOK_SECRET))
        self.assertFalse(security.verify_webhook_token(None, WEBHOOK_SECRET))
        # Empty secret rejects everything (misconfigured deployment).
        self.assertFalse(security.verify_webhook_token("anything", ""))


class AuthMiddlewareTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _use(self, **kwargs):
        settings = make_settings(**kwargs)
        return patch.object(security, "get_security_settings", lambda: settings)

    def _session(self, valid):
        return patch.object(auth_sessions, "session_is_valid", lambda token: valid)

    # ── 1. Local mode preserves current behavior ───────────────────────────

    def test_local_mode_dashboard_open(self):
        with self._use(require_auth=False):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    def test_local_mode_connect_token_not_blocked_by_auth(self):
        with self._use(require_auth=False):
            with patch("app.routes.sync.pluggy.create_connect_token", return_value="fake-token"):
                response = self.client.post("/connect-token")
        self.assertEqual(response.status_code, 200)

    # ── 2. Session-cookie gate ──────────────────────────────────────────────

    def test_auth_active_html_without_session_redirects_to_login(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/dashboard", headers={"accept": "text/html"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_auth_active_api_without_session_returns_401(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 401)

    def test_auth_active_with_invalid_cookie_rejected(self):
        self.client.cookies.set(SESSION_COOKIE_NAME, "bogus")
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 401)

    def test_auth_active_with_valid_cookie_returns_200(self):
        self.client.cookies.set(SESSION_COOKIE_NAME, "good")
        with self._use(require_auth=True), self._session(True):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    # ── 3. Public surface ───────────────────────────────────────────────────

    def test_static_public_even_with_auth_active(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/static/landing.js")
        self.assertEqual(response.status_code, 200)

    def test_landing_public_even_with_auth_active(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_login_endpoint_public_even_with_auth_active(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.post(
                "/auth/login", json={"email": "x@y.com", "password": "z"}
            )
        # Reached the route (returns its own 401), not blocked by the gate.
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password.")

    def test_dashboard_still_protected_with_public_landing(self):
        with self._use(require_auth=True), self._session(False):
            landing = self.client.get("/")
            dashboard = self.client.get("/dashboard", headers={"accept": "text/html"})
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(dashboard.status_code, 303)

    # ── 4. Health public/private ─────────────────────────────────────────────

    def test_health_public_when_configured(self):
        with self._use(require_auth=True, public_health=True), self._session(False):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_private_when_configured(self):
        with self._use(require_auth=True, public_health=False), self._session(False):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 401)

    def test_health_private_accessible_with_session(self):
        self.client.cookies.set(SESSION_COOKIE_NAME, "good")
        with self._use(require_auth=True, public_health=False), self._session(True):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    # ── 5. Sensitive endpoints protected ─────────────────────────────────────

    def test_connect_token_protected_and_pluggy_not_called(self):
        with self._use(require_auth=True), self._session(False):
            with patch("app.routes.sync.pluggy.create_connect_token") as mocked:
                response = self.client.post("/connect-token")
        self.assertEqual(response.status_code, 401)
        mocked.assert_not_called()

    def test_item_sync_protected_and_sync_not_started(self):
        with self._use(require_auth=True), self._session(False):
            with patch("app.routes.sync.run_sync_item") as mocked:
                response = self.client.post("/items/item-abc/sync")
        self.assertEqual(response.status_code, 401)
        mocked.assert_not_called()

    def test_snapshots_refresh_protected(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.post("/history/snapshots/refresh")
        self.assertEqual(response.status_code, 401)

    def test_debug_endpoint_protected(self):
        with self._use(require_auth=True), self._session(False):
            response = self.client.get("/debug/duplicate-transactions")
        self.assertEqual(response.status_code, 401)

    # ── 6. Webhook secret handling (unchanged logic) ─────────────────────────

    def test_webhook_without_token_rejected(self):
        with self._use(require_auth=True, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post("/webhooks/pluggy", json={"event": "ignored/event"})
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_with_wrong_token_rejected(self):
        with self._use(require_auth=True, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                "/webhooks/pluggy?token=wrong", json={"event": "ignored/event"}
            )
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_with_correct_token_reaches_route(self):
        with self._use(require_auth=True, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                f"/webhooks/pluggy?token={WEBHOOK_SECRET}",
                json={"event": "ignored/event"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json().get("action"), "ignored")

    def test_webhook_does_not_require_session(self):
        with self._use(require_auth=True, webhook_secret=WEBHOOK_SECRET), self._session(False):
            response = self.client.post(
                f"/webhooks/pluggy?token={WEBHOOK_SECRET}",
                json={"event": "ignored/event"},
            )
        self.assertNotEqual(response.status_code, 401)

    def test_webhook_rejected_when_secret_unset_and_auth_active(self):
        with self._use(require_auth=True, webhook_secret=""):
            response = self.client.post(
                "/webhooks/pluggy?token=anything", json={"event": "ignored/event"}
            )
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_local_mode_no_secret_is_open(self):
        with self._use(require_auth=False, webhook_secret=""):
            response = self.client.post("/webhooks/pluggy", json={"event": "ignored/event"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json().get("action"), "ignored")

    def test_webhook_local_mode_with_secret_requires_token(self):
        with self._use(require_auth=False, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post("/webhooks/pluggy", json={"event": "ignored/event"})
        self.assertEqual(response.status_code, 403)

    def test_webhook_local_mode_with_secret_correct_token_passes(self):
        with self._use(require_auth=False, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                f"/webhooks/pluggy?token={WEBHOOK_SECRET}",
                json={"event": "ignored/event"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json().get("action"), "ignored")


if __name__ == "__main__":
    unittest.main()
