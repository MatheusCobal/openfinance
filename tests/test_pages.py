import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app


class PageSmokeTest(unittest.TestCase):
    """Routing/navigation smoke tests.

    Main landing page: /dashboard (executive summary)
    Primary planning route: /planejamento (serves planejamento.html)
    Legacy aliases:
    - GET /  → 302 redirect to /dashboard
    - GET /custos-fixos → 302 redirect to /planejamento
    - GET /orcamento → 307 redirect to /planejamento
    Other screens:
    - GET /historico → Histórico HTML
    - GET /proximos → Próximos HTML
    - GET /regras → Regras HTML
    """

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
        # follow_redirects=False so we can assert redirect codes directly.
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_root_redirects_to_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_dashboard_loads(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("dashboard.js", response.text)
        # Dashboard must reuse the shared planning helpers, not its own logic.
        self.assertIn("planning_common.js", response.text)

    def test_planejamento_route_serves_page(self):
        response = self.client.get("/planejamento")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        # Must load the renamed JS bundle, not the old custos_fixos.js
        self.assertIn("planejamento.js", response.text)
        self.assertNotIn("custos_fixos.js", response.text)
        # Shared planning helpers must load before the page bundle.
        self.assertIn("planning_common.js", response.text)
        # Must not expose a "Criar custo recorrente" tab button
        self.assertNotIn("Criar custo recorrente", response.text)

    def test_custos_fixos_redirects_to_planejamento(self):
        response = self.client.get("/custos-fixos")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/planejamento")

    def test_historico_loads(self):
        response = self.client.get("/historico")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_proximos_loads(self):
        response = self.client.get("/proximos")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_regras_loads(self):
        response = self.client.get("/regras")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_orcamento_redirects_to_planejamento(self):
        response = self.client.get("/orcamento")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/planejamento")

    def test_dashboard_js_loads_pluggy_connect_sdk(self):
        # dashboard.js must contain the Pluggy CDN URL and the robust SDK loader
        # so the "Conectar banco" button works without a hard-coded <script> tag.
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn(
            "cdn.pluggy.ai/pluggy-connect/latest/pluggy-connect.js",
            js,
            "dashboard.js must reference the Pluggy Connect CDN URL",
        )
        self.assertIn(
            "ensurePluggyConnectSdkLoaded",
            js,
            "dashboard.js must define the SDK loader function",
        )
        self.assertIn(
            "window.PluggyConnect",
            js,
            "dashboard.js must use window.PluggyConnect (not bare PluggyConnect)",
        )
        # SDK load must happen before token fetch — ensurePluggyConnect must appear
        # before the connect-token fetch call in the source.
        sdk_pos = js.index("ensurePluggyConnectSdkLoaded")
        token_pos = js.index("connect-token")
        self.assertLess(sdk_pos, token_pos, "SDK loader must be defined before connect-token call")

    def test_dashboard_js_onsuccess_is_defensive_about_item_id(self):
        # onSuccess must handle data.itemId, data?.item?.id, and data?.id payloads.
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn(
            "data?.itemId || data?.item?.id || data?.id",
            js,
            "onSuccess must extract itemId defensively from all three payload shapes",
        )

    def test_dashboard_js_fetchjson_extracts_error_detail(self):
        # fetchJson must attempt to read the JSON body detail on error responses.
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn(
            "body?.detail",
            js,
            "fetchJson must extract detail from error response body",
        )

    def test_dashboard_js_has_no_stale_sdk_error_message(self):
        # The old fallback message that appeared when SDK wasn't loaded must be gone.
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "SDK Pluggy Connect não carregado",
            response.text,
            "Old stale error message must be removed from dashboard.js",
        )

    def test_dashboard_js_exposes_version_and_helpers_on_window(self):
        # The JS must expose key symbols on window so DevTools can confirm
        # the new version is actually executing (not a stale cached copy).
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        for symbol in (
            "DASHBOARD_JS_VERSION",
            "window.DASHBOARD_JS_VERSION",
            "window.ensurePluggyConnectSdkLoaded",
            "window.connectBank",
        ):
            self.assertIn(symbol, js, f"dashboard.js must assign {symbol!r}")

    def test_dashboard_js_uses_window_connectbank_in_listener(self):
        # The click listener must reference window.connectBank so it always
        # invokes the current definition even if the closure was cached.
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "window.connectBank",
            response.text,
            "btn-connect listener must use window.connectBank",
        )

    def test_dashboard_html_includes_pluggy_sdk_script_tag(self):
        # dashboard.html must load the Pluggy Connect SDK directly so
        # window.PluggyConnect is available before dashboard.js runs.
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "cdn.pluggy.ai/pluggy-connect/latest/pluggy-connect.js",
            response.text,
            "/dashboard HTML must contain a <script> tag for the Pluggy CDN",
        )

    def test_dashboard_html_uses_v15(self):
        # Ensure the browser busts the cache for the updated dashboard.js.
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("dashboard.js?v=15", response.text)

    def test_dashboard_js_uses_current_card_invoice_endpoint_for_invoice_card(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("fetchJson('/credit-card/current-invoice')", js)
        self.assertIn("currentCardInvoice", js)
        self.assertIn("const invoice = currentCardInvoice || {}", js)
        self.assertIn("currentCardInvoice?.categories", js)
        self.assertNotIn("fetchJson('/stats/monthly')", js)
        self.assertNotIn("cat.by_month?.[planningYM]", js)
        self.assertNotIn(
            "const invoice = capacity.credit_card_invoice || capacity.planning_invoice || {}",
            js,
        )

    def test_dashboard_html_has_bank_balance_container(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="bank-balance-card"', response.text)

    def test_dashboard_html_has_invoice_reconciliation_container(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="invoice-reconciliation"', response.text)

    def test_dashboard_html_has_category_containers(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="categories-grid"', response.text)
        self.assertIn('id="category-modal"', response.text)
        self.assertIn('id="modal-transactions-list"', response.text)

    def test_dashboard_js_has_render_invoice_reconciliation(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("renderInvoiceReconciliation", js)
        self.assertIn("currentCardInvoice?.reconciliation", js)
        self.assertIn("rec.category_total", js)
        self.assertIn("rec.refund_abs_total", js)
        # Reconciliation must never write back to currentCardInvoice
        self.assertNotIn("currentCardInvoice.amount =", js)
        self.assertNotIn("currentCardInvoice =", js.split("renderInvoiceReconciliation")[1].split("function ")[0])

    def test_dashboard_js_has_render_bank_balance(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("renderBankBalance", js)
        self.assertIn("fetchJson('/bank/balance-summary')", js)
        self.assertIn("bankBalance", js)
        # Bank balance widget must not use CREDIT data
        self.assertNotIn("currentCardInvoice.amount", js.split("renderBankBalance")[1].split("function ")[0])

    def test_static_files_do_not_use_indigo_classes(self):
        static_dir = Path("app/static")
        offenders = []
        for path in static_dir.iterdir():
            if path.is_file() and path.suffix in {".html", ".js", ".css"}:
                if "indigo" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path))
        self.assertEqual(offenders, [], "app/static must not contain indigo classes")

    def test_bank_balance_endpoint_exists(self):
        response = self.client.get("/bank/balance-summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total", data)
        self.assertIn("account_count", data)
        self.assertIn("accounts", data)
        self.assertIn("source", data)

    def test_dashboard_sub_routes_return_404(self):
        for path in (
            "/dashboard/snapshot",
            "/dashboard/credit-card-diagnostics?year_month=2026-06",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, f"Expected 404 for {path}")

    def test_removed_reserve_savings_routes_return_404(self):
        for path in (
            "/savings-target",
            "/savings-target/months/2026-06",
            "/emergency-reserve/monthly",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_sidebar_has_dashboard_link(self):
        # All pages must show a Dashboard nav item after its reintroduction.
        for path in ("/dashboard", "/historico", "/planejamento", "/regras", "/proximos"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("Dashboard", response.text, path)
            self.assertNotIn('href="/orcamento"', response.text, path)
            self.assertNotIn('href="/custos-fixos"', response.text, path)


class ConnectTokenEndpointTest(unittest.TestCase):
    """Tests for POST /connect-token with mocked Pluggy client.

    We never call the real Pluggy API in tests — all HTTP traffic is patched.
    """

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
        self.assertIn("accessToken", data, "Response must contain 'accessToken'")
        self.assertEqual(data["accessToken"], "fake-token-xyz")

    def test_connect_token_passes_item_id_to_pluggy(self):
        """itemId in request body must be forwarded to pluggy.create_connect_token."""
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
        """A 401/403 from Pluggy must surface as 401 with a helpful message."""
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
        """A 5xx from Pluggy must surface as 502."""
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
        """Calling without any body must not crash — defaults are applied."""
        with patch(
            "app.routes.sync.pluggy.create_connect_token",
            return_value="token-no-body",
        ):
            response = self.client.post("/connect-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accessToken"], "token-no-body")


if __name__ == "__main__":
    unittest.main()
