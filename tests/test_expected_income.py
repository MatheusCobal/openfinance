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
        all_entries = self.client.get("/expected-income", params={"include_inactive": True}).json()
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
                    ExpectedIncome(description="Salário", amount=Decimal("10000"), expected_day=5),
                    ExpectedIncome(description="Freela", amount=Decimal("2000"), expected_day=20),
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
                    date=self.today,  # always on-or-before today; day 5 may be future
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

    def test_monthly_breakdown_applies_override_for_target_month(self):
        with Session(self.engine) as session:
            session.add(
                ExpectedIncome(
                    id=1,
                    description="Salário",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.commit()

        # No override yet → effective amount equals base.
        breakdown = self.client.get(
            "/expected-income/by-month",
            params={"year_month": "2026-06"},
        ).json()
        self.assertEqual(breakdown["total"], 10000.0)
        self.assertFalse(breakdown["entries"][0]["is_override"])
        self.assertEqual(breakdown["entries"][0]["amount"], 10000.0)
        self.assertEqual(breakdown["entries"][0]["base_amount"], 10000.0)

        # Set an override for 2026-06.
        upserted = self.client.put(
            "/expected-income/1/overrides/2026-06",
            json={"amount": 11500},
        ).json()
        self.assertEqual(upserted["amount"], 11500.0)

        # June reflects the override; July still uses base.
        june = self.client.get("/expected-income/by-month", params={"year_month": "2026-06"}).json()
        july = self.client.get("/expected-income/by-month", params={"year_month": "2026-07"}).json()
        self.assertEqual(june["entries"][0]["amount"], 11500.0)
        self.assertTrue(june["entries"][0]["is_override"])
        self.assertEqual(july["entries"][0]["amount"], 10000.0)
        self.assertFalse(july["entries"][0]["is_override"])

        # Delete the override → back to base.
        self.assertEqual(
            self.client.delete("/expected-income/1/overrides/2026-06").status_code,
            204,
        )
        june_again = self.client.get(
            "/expected-income/by-month", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(june_again["entries"][0]["amount"], 10000.0)

    def test_upcoming_returns_consecutive_months(self):
        with Session(self.engine) as session:
            session.add(
                ExpectedIncome(
                    id=1,
                    description="Salário",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.commit()
        # Override only Aug 2026.
        self.client.put("/expected-income/1/overrides/2026-08", json={"amount": 12000})

        upcoming = self.client.get(
            "/expected-income/upcoming",
            params={"start_year_month": "2026-06", "months": 4},
        ).json()
        self.assertEqual(
            [m["year_month"] for m in upcoming], ["2026-06", "2026-07", "2026-08", "2026-09"]
        )
        totals = {m["year_month"]: m["total"] for m in upcoming}
        self.assertEqual(totals["2026-06"], 10000.0)
        self.assertEqual(totals["2026-07"], 10000.0)
        self.assertEqual(totals["2026-08"], 12000.0)
        self.assertEqual(totals["2026-09"], 10000.0)

    def test_remaining_clamped_to_zero_when_received_exceeds_expected(self):
        with Session(self.engine) as session:
            session.add(
                ExpectedIncome(description="Salário", amount=Decimal("5000"), expected_day=5)
            )
            session.add(
                Transaction(
                    id="tx-big-salary",
                    account_id="bank-1",
                    date=self.today,  # always on-or-before today; day 5 may be future
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
