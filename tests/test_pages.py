import unittest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app


class PageSmokeTest(unittest.TestCase):
    """Routing/navigation smoke tests for the simplified UI.

    Primary planning route: /planejamento (serves planejamento.html)
    Legacy aliases:
    - GET /  → 302 redirect to /planejamento
    - GET /custos-fixos → 302 redirect to /planejamento
    - GET /orcamento → 307 redirect to /planejamento
    Other screens:
    - GET /historico → Histórico HTML
    - GET /proximos → Próximos HTML
    - GET /regras → Regras HTML
    Removed routes:
    - Dashboard routes (/dashboard/*) → 404
    - Reserve/savings routes → 404
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

    def test_root_redirects_to_planejamento(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/planejamento")

    def test_planejamento_route_serves_page(self):
        response = self.client.get("/planejamento")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        # Must load the renamed JS bundle, not the old custos_fixos.js
        self.assertIn("planejamento.js", response.text)
        self.assertNotIn("custos_fixos.js", response.text)
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

    def test_dashboard_routes_return_404(self):
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

    def test_sidebar_has_no_dashboard_link(self):
        # Primary pages must not show a Dashboard nav item.
        for path in ("/historico", "/planejamento", "/regras", "/proximos"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn("Dashboard", response.text, path)
            self.assertNotIn('href="/orcamento"', response.text, path)
            self.assertNotIn('href="/custos-fixos"', response.text, path)


if __name__ == "__main__":
    unittest.main()
