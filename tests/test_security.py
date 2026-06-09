"""Tests for the minimal single-user auth layer (Item 9A).

The middleware reads security settings per request via
``app.security.get_security_settings``, so these tests patch that function to
control auth state deterministically — no environment ordering, no real secrets.
"""

import base64
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.security as security
from app.database import get_session
from app.main import app

ADMIN_TOKEN = "test-admin-token-123"
WEBHOOK_SECRET = "test-webhook-secret-xyz"


def make_settings(
    *,
    require_auth=False,
    admin_token="",
    public_health=True,
    webhook_secret="",
    env="local",
):
    # _env_file=None + explicit values: fully isolated from any local .env/os.environ.
    return security.SecuritySettings(
        _env_file=None,
        openfinance_env=env,
        openfinance_require_auth=require_auth,
        openfinance_admin_token=admin_token,
        openfinance_public_health=public_health,
        openfinance_webhook_secret=webhook_secret,
    )


def basic_header(token, username="anyuser"):
    raw = f"{username}:{token}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


class SecuritySettingsTest(unittest.TestCase):
    def test_defaults_are_local_and_open(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        self.assertEqual(settings.openfinance_env, "local")
        self.assertFalse(settings.openfinance_require_auth)
        self.assertEqual(settings.openfinance_admin_token, "")
        self.assertTrue(settings.openfinance_public_health)
        self.assertEqual(settings.openfinance_webhook_secret, "")

    def test_bool_parsed_from_env(self):
        with patch.dict(os.environ, {"OPENFINANCE_REQUIRE_AUTH": "true"}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        self.assertTrue(settings.openfinance_require_auth)

    def test_security_settings_do_not_require_pluggy_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = security.SecuritySettings(_env_file=None)
        # Sanity: this settings object is independent from Pluggy config.
        self.assertFalse(hasattr(settings, "pluggy_client_id"))


class AuthHelperTest(unittest.TestCase):
    def test_verify_basic_auth_accepts_correct_password(self):
        header = basic_header(ADMIN_TOKEN)["Authorization"]
        self.assertTrue(security.verify_basic_auth(header, ADMIN_TOKEN))

    def test_verify_basic_auth_ignores_username(self):
        header = basic_header(ADMIN_TOKEN, username="literally-anything")["Authorization"]
        self.assertTrue(security.verify_basic_auth(header, ADMIN_TOKEN))

    def test_verify_basic_auth_rejects_wrong_password(self):
        header = basic_header("wrong")["Authorization"]
        self.assertFalse(security.verify_basic_auth(header, ADMIN_TOKEN))

    def test_verify_basic_auth_rejects_missing_or_malformed(self):
        self.assertFalse(security.verify_basic_auth(None, ADMIN_TOKEN))
        self.assertFalse(security.verify_basic_auth("Bearer xyz", ADMIN_TOKEN))
        self.assertFalse(security.verify_basic_auth("Basic !!!notbase64", ADMIN_TOKEN))

    def test_verify_basic_auth_rejects_when_admin_token_empty(self):
        header = basic_header("")["Authorization"]
        self.assertFalse(security.verify_basic_auth(header, ""))

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
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _use(self, **kwargs):
        settings = make_settings(**kwargs)
        return patch.object(security, "get_security_settings", lambda: settings)

    # ── 1. Local mode preserves current behavior ───────────────────────────

    def test_local_mode_dashboard_open(self):
        with self._use(require_auth=False):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    def test_local_mode_connect_token_not_blocked_by_auth(self):
        with self._use(require_auth=False):
            with patch(
                "app.routes.sync.pluggy.create_connect_token",
                return_value="fake-token",
            ):
                response = self.client.post("/connect-token")
        self.assertNotEqual(response.status_code, 401)
        self.assertEqual(response.status_code, 200)

    # ── 2-4. Basic Auth lifecycle ───────────────────────────────────────────

    def test_auth_active_without_credentials_returns_401(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("WWW-Authenticate"), "Basic")

    def test_auth_active_with_wrong_credentials_returns_401(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.get("/dashboard", headers=basic_header("wrong"))
        self.assertEqual(response.status_code, 401)

    def test_auth_active_with_correct_credentials_returns_200(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.get("/dashboard", headers=basic_header(ADMIN_TOKEN))
        self.assertEqual(response.status_code, 200)

    # ── 5. Static always public ─────────────────────────────────────────────

    def test_static_public_even_with_auth_active(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)

    # ── 6-7. Health public/private ──────────────────────────────────────────

    def test_health_public_when_configured(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, public_health=True):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_private_when_configured(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, public_health=False):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 401)

    def test_health_private_accessible_with_credentials(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, public_health=False):
            response = self.client.get("/health", headers=basic_header(ADMIN_TOKEN))
        self.assertEqual(response.status_code, 200)

    # ── 8-11. Sensitive endpoints protected ─────────────────────────────────

    def test_connect_token_protected_and_pluggy_not_called(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            with patch("app.routes.sync.pluggy.create_connect_token") as mocked:
                response = self.client.post("/connect-token")
        self.assertEqual(response.status_code, 401)
        mocked.assert_not_called()

    def test_item_sync_protected_and_sync_not_started(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            with patch("app.routes.sync.run_sync_item") as mocked:
                response = self.client.post("/items/item-abc/sync")
        self.assertEqual(response.status_code, 401)
        mocked.assert_not_called()

    def test_snapshots_refresh_protected(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.post("/history/snapshots/refresh")
        self.assertEqual(response.status_code, 401)

    def test_debug_endpoint_protected(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN):
            response = self.client.get("/debug/duplicate-transactions")
        self.assertEqual(response.status_code, 401)

    # ── Fail-safe: auth required but no admin token ─────────────────────────

    def test_auth_required_without_admin_token_returns_500(self):
        with self._use(require_auth=True, admin_token=""):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 500)

    # ── 12. Webhook secret handling ─────────────────────────────────────────

    def test_webhook_without_token_rejected(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post("/webhooks/pluggy", json={"event": "ignored/event"})
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_with_wrong_token_rejected(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                "/webhooks/pluggy?token=wrong", json={"event": "ignored/event"}
            )
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_with_correct_token_reaches_route(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                f"/webhooks/pluggy?token={WEBHOOK_SECRET}",
                json={"event": "ignored/event"},
            )
        # Reached the route (not blocked by auth) — benign event returns 202.
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json().get("action"), "ignored")

    def test_webhook_does_not_require_basic_auth(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                f"/webhooks/pluggy?token={WEBHOOK_SECRET}",
                json={"event": "ignored/event"},
            )
        self.assertNotEqual(response.status_code, 401)

    def test_admin_token_does_not_work_as_webhook_token(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=WEBHOOK_SECRET):
            response = self.client.post(
                f"/webhooks/pluggy?token={ADMIN_TOKEN}",
                json={"event": "ignored/event"},
            )
        self.assertIn(response.status_code, (401, 403))

    def test_webhook_rejected_when_secret_unset_and_auth_active(self):
        with self._use(require_auth=True, admin_token=ADMIN_TOKEN, webhook_secret=""):
            response = self.client.post(
                "/webhooks/pluggy?token=anything", json={"event": "ignored/event"}
            )
        self.assertIn(response.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
