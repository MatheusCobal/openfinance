import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import (
    Account,
    BankIncomeMonth,
    ExpectedIncome,
    Item,
    Transaction,
)


class ExpectedIncomeTest(unittest.TestCase):
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

        self.today = date.today()
        self.current_month = self.today.strftime("%Y-%m")

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-1",
                    name="Checking",
                    type="BANK",
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_create_list_update_delete(self):
        create = self.client.post(
            "/expected-income",
            json={"description": "Salário", "amount": 10000, "expected_day": 5},
        ).json()
        self.assertEqual(create["amount"], 10000.0)
        self.assertTrue(create["active"])

        listed = self.client.get("/expected-income").json()
        self.assertEqual(len(listed), 1)

        patched = self.client.patch(
            f"/expected-income/{create['id']}",
            json={"amount": 12000, "active": False},
        ).json()
        self.assertEqual(patched["amount"], 12000.0)
        self.assertFalse(patched["active"])

        active_only = self.client.get("/expected-income").json()
        self.assertEqual(active_only, [])
        all_entries = self.client.get(
            "/expected-income", params={"include_inactive": True}
        ).json()
        self.assertEqual(len(all_entries), 1)

        self.assertEqual(
            self.client.delete(f"/expected-income/{create['id']}").status_code,
            204,
        )
        self.assertEqual(self.client.get("/expected-income").json(), [])

    def test_create_rejects_invalid_input(self):
        self.assertEqual(
            self.client.post(
                "/expected-income",
                json={"description": "", "amount": 100, "expected_day": 5},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/expected-income",
                json={"description": "x", "amount": -1, "expected_day": 5},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/expected-income",
                json={"description": "x", "amount": 100, "expected_day": 32},
            ).status_code,
            400,
        )

    def test_forecast_subtracts_received_from_expected(self):
        # Seed expected income.
        with Session(self.engine) as session:
            session.add_all(
                [
                    ExpectedIncome(
                        description="Salário", amount=Decimal("10000"), expected_day=5
                    ),
                    ExpectedIncome(
                        description="Freela", amount=Decimal("2000"), expected_day=20
                    ),
                    # Inactive entries shouldn't count.
                    ExpectedIncome(
                        description="Antigo",
                        amount=Decimal("99999"),
                        expected_day=10,
                        active=False,
                    ),
                ]
            )
            # Provide a real bank-income transaction so the snapshot refresh
            # produces a row for the current month.
            session.add(
                Transaction(
                    id="tx-salary-received",
                    account_id="bank-1",
                    date=date(self.today.year, self.today.month, 5),
                    amount=Decimal("8000"),
                    description="Salário Empresa",
                    category="Salary",
                )
            )
            session.commit()

        forecast = self.client.get(
            "/expected-income/forecast",
            params={"year_month": self.current_month},
        ).json()

        self.assertEqual(forecast["expected_total"], 12000.0)
        self.assertEqual(forecast["received_total"], 8000.0)
        self.assertEqual(forecast["remaining_estimate"], 4000.0)
        self.assertEqual(len(forecast["entries"]), 2)

    def test_forecast_rejects_bad_month(self):
        self.assertEqual(
            self.client.get(
                "/expected-income/forecast", params={"year_month": "not-a-month"}
            ).status_code,
            400,
        )

    def test_remaining_clamped_to_zero_when_received_exceeds_expected(self):
        with Session(self.engine) as session:
            session.add(
                ExpectedIncome(
                    description="Salário", amount=Decimal("5000"), expected_day=5
                )
            )
            session.add(
                Transaction(
                    id="tx-big-salary",
                    account_id="bank-1",
                    date=date(self.today.year, self.today.month, 5),
                    amount=Decimal("9000"),
                    description="Salário Empresa",
                    category="Salary",
                )
            )
            session.commit()

        forecast = self.client.get(
            "/expected-income/forecast",
            params={"year_month": self.current_month},
        ).json()

        self.assertEqual(forecast["expected_total"], 5000.0)
        self.assertEqual(forecast["received_total"], 9000.0)
        self.assertEqual(forecast["remaining_estimate"], 0.0)


if __name__ == "__main__":
    unittest.main()
