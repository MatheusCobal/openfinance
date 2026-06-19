import json
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.security as security
from app.auth import sessions as auth_sessions
from app.auth.sessions import SESSION_COOKIE_NAME
from app.database import get_session
from app.main import app


INTERNAL_ROUTES = ("/dashboard", "/planejamento", "/historico", "/proximos", "/regras")


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


class StaticAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.assets.append(value)


class PageSmokeTest(unittest.TestCase):
    """Routing/navigation smoke tests for the public landing and React app shell."""

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

    def _use_auth(self, **kwargs):
        settings = make_settings(**kwargs)
        return patch.object(security, "get_security_settings", lambda: settings)

    def _session(self, valid):
        return patch.object(auth_sessions, "session_is_valid", lambda token: valid)

    def test_root_serves_public_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("landing.css", response.text)
        self.assertIn("landing.js", response.text)
        self.assertIn('href="/dashboard"', response.text)
        self.assertIn("Acessar minha conta", response.text)

    def test_landing_has_secondary_cta(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ver como funciona", response.text)
        self.assertIn('href="#como-funciona"', response.text)

    def test_landing_does_not_load_authenticated_app_bundles_or_sdks(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertNotIn("planning_common.js", html)
        self.assertNotIn("dashboard.js", html)
        self.assertNotIn("/static/react/", html)
        self.assertNotIn("cdn.pluggy.ai", html)

    def test_landing_js_makes_no_api_calls(self):
        response = self.client.get("/static/landing.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertNotIn("fetch(", js)
        self.assertNotIn("XMLHttpRequest", js)

    def test_landing_uses_cache_busted_assets(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("landing.css?v=", response.text)
        self.assertIn("landing.js?v=", response.text)

    def test_login_route_serves_react_app_shell(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn('<div id="root"></div>', response.text)

    def test_internal_routes_serve_react_app_shell(self):
        for path in INTERNAL_ROUTES:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])
                self.assertIn('<div id="root"></div>', response.text)
                self.assertNotIn("dashboard.js", response.text)
                self.assertNotIn("planejamento.js", response.text)
                self.assertNotIn("historico.js", response.text)
                self.assertNotIn("proximos.js", response.text)
                self.assertNotIn("regras.js", response.text)

    def test_internal_routes_are_protected_when_auth_is_active(self):
        with self._use_auth(require_auth=True), self._session(False):
            for path in INTERNAL_ROUTES:
                with self.subTest(path=path):
                    response = self.client.get(path, headers={"accept": "text/html"})
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(response.headers["location"], "/login")

    def test_internal_routes_return_react_app_with_valid_session(self):
        self.client.cookies.set(SESSION_COOKIE_NAME, "good")
        with self._use_auth(require_auth=True), self._session(True):
            for path in INTERNAL_ROUTES:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('<div id="root"></div>', response.text)

    def test_public_landing_stays_public_when_auth_is_active(self):
        with self._use_auth(require_auth=True), self._session(False):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_apis_continue_protected_when_auth_is_active(self):
        with self._use_auth(require_auth=True), self._session(False):
            response = self.client.get("/planning/month/2026-07")
        self.assertEqual(response.status_code, 401)

    def test_custos_fixos_redirects_to_planejamento(self):
        response = self.client.get("/custos-fixos")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/planejamento")

    def test_orcamento_redirects_to_planejamento(self):
        response = self.client.get("/orcamento")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/planejamento")

    def test_health_works(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_react_build_assets_are_served_when_build_exists(self):
        index = Path("app/static/react/index.html")
        if not index.is_file():
            self.skipTest("React build not present; run npm run build to verify built assets.")
        parser = StaticAssetParser()
        parser.feed(index.read_text(encoding="utf-8"))
        assets = [asset for asset in parser.assets if asset.startswith("/static/react/")]
        self.assertGreaterEqual(len(assets), 2)
        for asset in assets:
            response = self.client.get(asset)
            self.assertEqual(response.status_code, 200, asset)

    def test_local_static_assets_referenced_by_landing_exist(self):
        static_dir = Path("app/static")
        parser = StaticAssetParser()
        parser.feed((static_dir / "landing.html").read_text(encoding="utf-8"))
        missing = []
        for asset in parser.assets:
            parsed = urlsplit(asset)
            if parsed.scheme or parsed.netloc:
                continue
            if not parsed.path.startswith("/static/"):
                continue
            target = static_dir / parsed.path.removeprefix("/static/")
            if not target.is_file():
                missing.append(asset)
        self.assertEqual(missing, [])

    def test_bank_balance_endpoint_exists(self):
        response = self.client.get("/bank/balance-summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total", data)
        self.assertIn("account_count", data)
        self.assertIn("accounts", data)
        self.assertIn("source", data)

    def test_removed_reserve_savings_routes_return_404(self):
        for path in (
            "/savings-target",
            "/savings-target/months/2026-06",
            "/emergency-reserve/monthly",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)


class ConnectTokenEndpointTest(unittest.TestCase):
    """Tests for POST /connect-token with mocked Pluggy client."""

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

    def test_connect_token_returns_access_token(self):
        with patch(
            "app.routes.sync.pluggy.create_connect_token",
            return_value="fake-token-xyz",
        ):
            response = self.client.post(
                "/connect-token",
                json={},
                headers={"content-type": "application/json"},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("accessToken", data)
        self.assertEqual(data["accessToken"], "fake-token-xyz")

    def test_connect_token_passes_item_id_to_pluggy(self):
        calls = []

        def fake_create(client_user_id=None, item_id=None):
            calls.append({"client_user_id": client_user_id, "item_id": item_id})
            return "token-with-item"

        with patch("app.routes.sync.pluggy.create_connect_token", side_effect=fake_create):
            response = self.client.post(
                "/connect-token",
                json={"itemId": "item-abc123"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0]["item_id"], "item-abc123")

    def test_connect_token_returns_401_on_pluggy_credential_error(self):
        mock_response = httpx.Response(401, text="Unauthorized")
        exc = httpx.HTTPStatusError(
            "401 Unauthorized", request=httpx.Request("POST", "/"), response=mock_response
        )
        with patch(
            "app.routes.sync.pluggy.create_connect_token",
            side_effect=exc,
        ):
            response = self.client.post("/connect-token", json={})
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertIn("PLUGGY_CLIENT_ID", body.get("detail", ""))

    def test_connect_token_returns_502_on_pluggy_server_error(self):
        mock_response = httpx.Response(503, text="Service Unavailable")
        exc = httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "/"), response=mock_response
        )
        with patch(
            "app.routes.sync.pluggy.create_connect_token",
            side_effect=exc,
        ):
            response = self.client.post("/connect-token", json={})
        self.assertEqual(response.status_code, 502)

    def test_connect_token_no_body_still_works(self):
        with patch(
            "app.routes.sync.pluggy.create_connect_token",
            return_value="token-no-body",
        ):
            response = self.client.post("/connect-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accessToken"], "token-no-body")


class ReactSourceContractTest(unittest.TestCase):
    """Fast source-level checks for the new frontend architecture."""

    def test_frontend_package_uses_required_stack(self):
        package = json.loads(Path("frontend/package.json").read_text(encoding="utf-8"))
        deps = {**package["dependencies"], **package["devDependencies"]}
        for name in ("react", "react-dom", "react-router-dom", "vite", "typescript", "tailwindcss"):
            self.assertIn(name, deps)

    def test_vite_build_targets_fastapi_static_react_dir(self):
        config = Path("frontend/vite.config.ts").read_text(encoding="utf-8")
        self.assertIn('base: "/static/react/"', config)
        self.assertIn('outDir: "../app/static/react"', config)

    def test_internal_routes_are_declared_in_react_router(self):
        routes = Path("frontend/src/routes.tsx").read_text(encoding="utf-8")
        for path in INTERNAL_ROUTES:
            self.assertIn(f'path: "{path}"', routes)

    def test_old_internal_html_files_are_not_page_route_targets(self):
        pages = Path("app/routes/pages.py").read_text(encoding="utf-8")
        for name in (
            "dashboard.html",
            "planejamento.html",
            "historico.html",
            "proximos.html",
            "regras.html",
        ):
            self.assertNotIn(name, pages)
        self.assertIn("react_app()", pages)

    def test_old_internal_static_pages_were_removed(self):
        static_dir = Path("app/static")
        for name in (
            "dashboard.html",
            "dashboard.js",
            "planejamento.html",
            "planejamento.js",
            "historico.html",
            "historico.js",
            "proximos.html",
            "proximos.js",
            "regras.html",
            "regras.js",
            "planning_common.js",
            "styles.css",
        ):
            self.assertFalse((static_dir / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
