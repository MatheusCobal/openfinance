import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app


class StaticAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.assets.append(value)


class PageSmokeTest(unittest.TestCase):
    """Routing/navigation smoke tests.

    Public landing page: / (institutional/product page, no financial data)
    Main app page: /dashboard (executive summary)
    Primary planning route: /planejamento (serves planejamento.html)
    Legacy aliases:
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

    def test_root_serves_public_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("landing.css", response.text)
        self.assertIn("landing.js", response.text)

    def test_landing_has_primary_cta_to_app(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/dashboard"', response.text)
        self.assertIn("Acessar minha conta", response.text)

    def test_landing_has_secondary_cta(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ver como funciona", response.text)
        self.assertIn('href="#como-funciona"', response.text)

    def test_landing_does_not_load_app_bundles_or_sdks(self):
        # The landing page is static marketing content: it must not pull the
        # app bundles nor the Pluggy SDK (no financial data, no API surface).
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertNotIn("planning_common.js", html)
        self.assertNotIn("dashboard.js", html)
        self.assertNotIn("cdn.pluggy.ai", html)

    def test_landing_js_makes_no_api_calls(self):
        # Critical: any fetch() to a protected endpoint would trigger the
        # browser Basic Auth popup on the public page when auth is enabled.
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

    def test_regras_html_explains_safe_rule_preview(self):
        response = self.client.get("/regras")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("regras.js?v=20260610-1", html)
        self.assertIn("Preview seguro", html)
        self.assertIn("Pré-visualizar não grava nada", html)
        self.assertIn("Nenhuma regra criada ainda", html)

    def test_regras_js_renders_auditable_preview_and_friendly_errors(self):
        response = self.client.get("/static/regras.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("friendlyErrorMessage", js)
        self.assertIn("rawPluggySummary", js)
        self.assertIn("Pluggy bruto", js)
        self.assertIn("Classificação atual", js)
        self.assertIn("Nova classificação", js)
        self.assertIn("Preview calculado. Nenhum dado foi alterado.", js)

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

    def test_dashboard_html_uses_current_version(self):
        # Ensure the browser busts the cache for the updated dashboard.js.
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("dashboard.js?v=20260610-1", response.text)

    def test_dashboard_js_uses_current_card_invoice_endpoint_for_invoice_card(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("fetchJson('/credit-card/current-invoice')", js)
        self.assertIn("currentCardInvoice", js)
        self.assertIn("const invoice = currentCardInvoice || {}", js)
        self.assertIn("quebra por categoria usa a classificação Pluggy-based", js)
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

    def test_dashboard_html_has_hero_and_secondary_card_layout(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="dashboard-primary-grid"', response.text)
        self.assertIn('id="hero-card"', response.text)
        self.assertIn('id="dashboard-secondary-grid"', response.text)
        self.assertLess(
            response.text.index('id="hero-card"'),
            response.text.index('id="bank-balance-card"'),
        )

    def test_dashboard_html_has_invoice_reconciliation_container(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="invoice-card-content"', response.text)
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
        self.assertIn("Classificação por categoria", js)
        self.assertIn("classificação Pluggy-based da 10D-B", js)
        self.assertIn("rec.refund_abs_total", js)
        # Reconciliation must never write back to currentCardInvoice
        self.assertNotIn("currentCardInvoice.amount =", js)
        self.assertNotIn(
            "currentCardInvoice =", js.split("renderInvoiceReconciliation")[1].split("function ")[0]
        )

    def test_dashboard_js_has_render_bank_balance(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        js = response.text
        self.assertIn("renderBankBalance", js)
        self.assertIn("fetchJson('/bank/balance-summary')", js)
        self.assertIn("bankBalance", js)
        # Bank balance widget must not use CREDIT data
        self.assertNotIn(
            "currentCardInvoice.amount", js.split("renderBankBalance")[1].split("function ")[0]
        )

    def test_static_files_do_not_use_indigo_classes(self):
        static_dir = Path("app/static")
        offenders = []
        for path in static_dir.iterdir():
            if path.is_file() and path.suffix in {".html", ".js", ".css"}:
                if "indigo" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path))
        self.assertEqual(offenders, [], "app/static must not contain indigo classes")

    def test_local_static_assets_referenced_by_html_exist(self):
        static_dir = Path("app/static")
        missing = []
        for html_path in static_dir.glob("*.html"):
            parser = StaticAssetParser()
            parser.feed(html_path.read_text(encoding="utf-8"))
            for asset in parser.assets:
                parsed = urlsplit(asset)
                if parsed.scheme or parsed.netloc:
                    continue
                if not parsed.path.startswith("/static/"):
                    continue
                target = static_dir / parsed.path.removeprefix("/static/")
                if not target.is_file():
                    missing.append(f"{html_path}: {asset}")
        self.assertEqual(missing, [])

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


class DashboardCapacityTest(unittest.TestCase):
    """Tests that the dashboard uses currentCardInvoice.amount in capacity calculations."""

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

    def _get_js(self):
        response = self.client.get("/static/dashboard.js")
        self.assertEqual(response.status_code, 200)
        return response.text

    def _extract_fn(self, js, name):
        start = js.index(f"function {name}")
        end = js.index("\nfunction ", start + 1)
        return js[start:end]

    def test_dashboard_html_uses_current_version(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("dashboard.js?v=20260610-1", response.text)

    def test_dashboard_js_has_build_dashboard_capacity(self):
        js = self._get_js()
        self.assertIn("function buildDashboardCapacity", js)

    def test_build_dashboard_capacity_uses_current_invoice_amount(self):
        js = self._get_js()
        fn_body = self._extract_fn(js, "buildDashboardCapacity")
        self.assertIn("cardInvoice?.amount ?? cardInvoice?.adjusted_total", fn_body)
        self.assertIn("hasCurrentInvoiceAmount", fn_body)
        self.assertIn("invoiceIncludedAmount(planningCapacity)", fn_body)
        self.assertNotIn("planning_invoice", fn_body)

    def test_build_dashboard_capacity_formula(self):
        js = self._get_js()
        fn_body = self._extract_fn(js, "buildDashboardCapacity")
        self.assertIn("availableToSpend = hasCurrentInvoiceAmount", fn_body)
        self.assertIn("planningAvailable + planningInvoiceImpact - currentInvoiceAmount", fn_body)
        self.assertIn(": planningAvailable", fn_body)

    def test_build_dashboard_capacity_documents_dashboard_invoice_swap(self):
        js = self._get_js()
        fn_body = self._extract_fn(js, "buildDashboardCapacity")
        self.assertIn("Planejamento calcula a capacidade mensal", fn_body)
        self.assertIn("troca somente esse componente pela fatura atual operacional", fn_body)

    def test_dashboard_capacity_formula_examples(self):
        def dashboard_available(
            planning_available, planning_invoice_impact, current_invoice_amount
        ):
            if current_invoice_amount is None:
                return planning_available
            return planning_available + planning_invoice_impact - current_invoice_amount

        self.assertEqual(dashboard_available(5000, 2000, 3000), 4000)
        self.assertEqual(dashboard_available(5000, 2000, 1000), 6000)
        self.assertEqual(dashboard_available(5000, 2000, None), 5000)

    def test_build_dashboard_capacity_variable_remaining_formula(self):
        js = self._get_js()
        fn_body = self._extract_fn(js, "buildDashboardCapacity")
        self.assertIn("variableRemaining = variableBudget - variableUsed", fn_body)

    def test_build_dashboard_capacity_negative_status_is_over(self):
        js = self._get_js()
        fn_body = self._extract_fn(js, "buildDashboardCapacity")
        self.assertIn("availableToSpend >= 0", fn_body)
        self.assertIn("status = 'over'", fn_body)

    def test_render_hero_uses_build_dashboard_capacity(self):
        js = self._get_js()
        hero_body = self._extract_fn(js, "renderHero")
        self.assertIn("buildDashboardCapacity", hero_body)
        self.assertNotIn("capacity.budget_available_to_spend", hero_body)
        self.assertNotIn("capacity.plan_status", hero_body)

    def test_render_hero_shows_fatura_vigente_no_calculo(self):
        js = self._get_js()
        self.assertIn("Fatura vigente no cálculo", js)
        self.assertNotIn("No cálculo:", js)

    def test_render_summary_cards_variable_used_does_not_use_invoice_fields(self):
        js = self._get_js()
        summary_body = self._extract_fn(js, "renderSummaryCards")
        self.assertNotIn("credit_card_invoice", summary_body)
        self.assertNotIn("planning_invoice", summary_body)
        self.assertNotIn("invoiceIncludedAmount", summary_body)

    def test_planning_month_and_invoice_endpoints_still_fetched(self):
        js = self._get_js()
        self.assertIn("/planning/month/", js)
        self.assertIn("fetchJson('/credit-card/current-invoice')", js)
        self.assertIn("fetchJson('/bank/balance-summary')", js)

    def test_planning_month_route_backend_unchanged(self):
        response = self.client.get("/planning/month/2026-07")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("capacity", data)

    def test_current_invoice_endpoint_still_reachable(self):
        response = self.client.get("/credit-card/current-invoice")
        self.assertEqual(response.status_code, 200)

    def test_bank_balance_endpoint_still_reachable(self):
        response = self.client.get("/bank/balance-summary")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_js_does_not_use_stats_monthly(self):
        js = self._get_js()
        self.assertNotIn("fetchJson('/stats/monthly')", js)

    def test_static_files_no_indigo_classes(self):
        static_dir = Path("app/static")
        offenders = []
        for path in static_dir.iterdir():
            if path.is_file() and path.suffix in {".html", ".js", ".css"}:
                if "indigo" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path))
        self.assertEqual(offenders, [], "app/static must not contain indigo classes")


class FrontendHardeningTest(unittest.TestCase):
    """Static checks that harden the frontend namespace and loading order.

    These tests run against the source files directly (no HTTP) so they are
    fast and do not require a running server.
    """

    SHARED_SYMBOLS = [
        "currency",
        "MONTH_LABELS",
        "currentYearMonth",
        "getDefaultPlanningMonth",
        "shiftYearMonth",
        "formatMonthShort",
        "asMoneyNumber",
        "normalizePlanningOverview",
        "invoiceIncludedAmount",
        "PLAN_STATUS_LABELS",
        "planStatusLabel",
    ]

    def _read(self, relative_path: str) -> str:
        return Path(relative_path).read_text(encoding="utf-8")

    # ── Script loading order ────────────────────────────────────────────────

    def test_planning_common_loads_before_dashboard_js(self):
        html = self._read("app/static/dashboard.html")
        self.assertLess(
            html.index("planning_common.js"),
            html.index("dashboard.js"),
            "planning_common.js must appear before dashboard.js in dashboard.html",
        )

    def test_planning_common_loads_before_planejamento_js(self):
        html = self._read("app/static/planejamento.html")
        self.assertLess(
            html.index("planning_common.js"),
            html.index("planejamento.js"),
            "planning_common.js must appear before planejamento.js in planejamento.html",
        )

    # ── Namespace ───────────────────────────────────────────────────────────

    def test_planning_common_exposes_namespace(self):
        js = self._read("app/static/planning_common.js")
        self.assertIn("window.OpenFinancePlanning", js)
        for sym in self.SHARED_SYMBOLS:
            self.assertIn(sym, js, f"window.OpenFinancePlanning must include {sym!r}")

    def test_dashboard_captures_planning_namespace(self):
        js = self._read("app/static/dashboard.js")
        self.assertIn(
            "window.OpenFinancePlanning",
            js,
            "dashboard.js must reference window.OpenFinancePlanning",
        )

    def test_planejamento_captures_planning_namespace(self):
        js = self._read("app/static/planejamento.js")
        self.assertIn(
            "window.OpenFinancePlanning",
            js,
            "planejamento.js must reference window.OpenFinancePlanning",
        )

    # ── Anti-collision: bundles must not redeclare shared symbols ───────────

    def test_dashboard_js_does_not_redeclare_shared_symbols(self):
        js = self._read("app/static/dashboard.js")
        for sym in self.SHARED_SYMBOLS:
            for keyword in ("const", "let", "var"):
                declaration = f"{keyword} {sym}"
                self.assertNotIn(
                    declaration,
                    js,
                    f"dashboard.js must not redeclare {sym!r} (would collide with planning_common.js global)",
                )

    def test_planejamento_js_does_not_redeclare_shared_symbols(self):
        js = self._read("app/static/planejamento.js")
        for sym in self.SHARED_SYMBOLS:
            for keyword in ("const", "let", "var"):
                declaration = f"{keyword} {sym}"
                self.assertNotIn(
                    declaration,
                    js,
                    f"planejamento.js must not redeclare {sym!r} (would collide with planning_common.js global)",
                )

    # ── CDN placement: each CDN only on intended pages ──────────────────────

    def test_pluggy_sdk_only_in_dashboard(self):
        pluggy_cdn = "cdn.pluggy.ai"
        for name in ("historico.html", "planejamento.html", "proximos.html", "regras.html"):
            html = self._read(f"app/static/{name}")
            self.assertNotIn(pluggy_cdn, html, f"Pluggy SDK CDN must not appear in {name}")
        self.assertIn(pluggy_cdn, self._read("app/static/dashboard.html"))

    def test_chartjs_only_in_historico_and_proximos(self):
        chartjs_cdn = "chart.js"
        for name in ("dashboard.html", "planejamento.html", "regras.html"):
            html = self._read(f"app/static/{name}")
            self.assertNotIn(chartjs_cdn, html.lower(), f"Chart.js CDN must not appear in {name}")
        for name in ("historico.html", "proximos.html"):
            self.assertIn(chartjs_cdn, self._read(f"app/static/{name}").lower())

    def test_planning_common_not_loaded_in_standalone_pages(self):
        for name in ("historico.html", "proximos.html", "regras.html"):
            html = self._read(f"app/static/{name}")
            self.assertNotIn(
                "planning_common.js",
                html,
                f"planning_common.js must not be loaded in {name} (not needed there)",
            )


if __name__ == "__main__":
    unittest.main()
