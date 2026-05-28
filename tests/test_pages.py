import unittest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app


class PageSmokeTest(unittest.TestCase):
    """Routing/navigation smoke tests for the simplified UI.

    These assert the pages and the dashboard snapshot endpoint respond, and
    that /orcamento now redirects into Planejamento (/custos-fixos).
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
        # follow_redirects=False so we can assert the 307 on /orcamento.
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_dashboard_snapshot_returns_json(self):
        response = self.client.get("/dashboard/snapshot")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # Empty DB → zeroed but well-formed snapshot, never a 500.
        for key in ("bank", "credit", "investments"):
            self.assertIn(key, body)
        self.assertIn("total", body["bank"])
        self.assertIn("used", body["credit"])
        self.assertIn("reserve_total", body["investments"])

    def test_index_overview_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Overview", response.text)
        # Dashboard must use the overview script, not the transactions one.
        self.assertIn("/static/dashboard.js", response.text)
        # And must NOT pull the transaction-management bundle.
        self.assertNotIn("/static/transacoes.js", response.text)

    def test_transacoes_page_loads(self):
        response = self.client.get("/transacoes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Transações", response.text)
        self.assertIn("/static/transacoes.js", response.text)

    def test_orcamento_redirects_to_custos_fixos(self):
        response = self.client.get("/orcamento")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/custos-fixos")

    def test_custos_fixos_loads(self):
        response = self.client.get("/custos-fixos")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_historico_loads(self):
        response = self.client.get("/historico")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_sidebar_has_no_orcamento_link(self):
        # Every primary page should route to /custos-fixos for Planejamento,
        # never to the deprecated /orcamento screen.
        for path in ("/", "/transacoes", "/historico", "/custos-fixos", "/regras"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn('href="/orcamento"', response.text, path)


if __name__ == "__main__":
    unittest.main()
