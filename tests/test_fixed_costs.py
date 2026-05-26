import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, ExpectedIncome, Item, Transaction


class FixedCostsTest(unittest.TestCase):
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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit",
                    type="CREDIT",
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_create_list_update_delete_fixed_costs(self):
        category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Moradia", "color": "#0ea5e9", "sort_order": 1},
        ).json()
        self.assertEqual(category["name"], "Moradia")

        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Aluguel",
                "amount": 2500,
                "due_day": 5,
            },
        ).json()
        self.assertEqual(cost["amount"], 2500.0)
        self.assertTrue(cost["active"])

        listed = self.client.get("/fixed-costs").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["category_name"], "Moradia")

        patched = self.client.patch(
            f"/fixed-costs/{cost['id']}",
            json={"amount": 2600, "active": False},
        ).json()
        self.assertEqual(patched["amount"], 2600.0)
        self.assertFalse(patched["active"])

        self.assertEqual(self.client.get("/fixed-costs").json(), [])
        all_rows = self.client.get(
            "/fixed-costs", params={"include_inactive": True}
        ).json()
        self.assertEqual(len(all_rows), 1)

        self.assertEqual(
            self.client.delete(f"/fixed-costs/{cost['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(
                f"/fixed-cost-categories/{category['id']}"
            ).status_code,
            204,
        )

    def test_monthly_breakdown_applies_override(self):
        category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Escola", "color": "#f97316"},
        ).json()
        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Mensalidade",
                "amount": 1800,
                "due_day": 10,
            },
        ).json()

        base = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(base["total"], 1800.0)
        self.assertFalse(base["entries"][0]["is_override"])

        override = self.client.put(
            f"/fixed-costs/{cost['id']}/overrides/2026-06",
            json={"amount": 1950},
        ).json()
        self.assertEqual(override["amount"], 1950.0)

        june = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        july = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-07"}
        ).json()
        self.assertEqual(june["total"], 1950.0)
        self.assertTrue(june["entries"][0]["is_override"])
        self.assertEqual(july["total"], 1800.0)

        self.assertEqual(
            self.client.delete(
                f"/fixed-costs/{cost['id']}/overrides/2026-06"
            ).status_code,
            204,
        )
        june_again = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(june_again["total"], 1800.0)

    def test_spending_capacity_combines_income_fixed_costs_and_invoice(self):
        with Session(self.engine) as session:
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.add(
                Transaction(
                    id="tx-card-1",
                    account_id="credit-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("1200"),
                    description="Compra",
                    category="Shopping",
                )
            )
            session.commit()

        category = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Condominio",
                "amount": 2000,
                "due_day": 8,
            },
        )

        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-06"}
        ).json()

        self.assertEqual(capacity["expected_income_total"], 10000.0)
        self.assertEqual(capacity["fixed_cost_total"], 2000.0)
        self.assertEqual(capacity["card_invoice_total"], 1200.0)
        self.assertEqual(capacity["planned_after_fixed_costs"], 8000.0)
        self.assertEqual(capacity["remaining_after_invoice"], 6800.0)

    def test_validates_inputs(self):
        self.assertEqual(
            self.client.post(
                "/fixed-cost-categories", json={"name": ""}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/fixed-costs",
                json={
                    "category_id": 999,
                    "description": "x",
                    "amount": -1,
                    "due_day": 1,
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/fixed-costs/by-month", params={"year_month": "bad"}
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
