import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.categorization import normalize_description
from app.database import get_session
from app.main import app
from app.models import (
    Account,
    BankIncomeExclusionRule,
    Budget,
    BudgetOverride,
    Category,
    CategoryRule,
    DescriptionCategoryRule,
    IgnoredDescriptionRule,
    Item,
    Transaction,
)


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


class BackendRegressionTest(unittest.TestCase):
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
        self.current_month_day = date(self.today.year, self.today.month, 1)
        self.next_month_day = next_month(self.current_month_day)
        self._seed_base_data()

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed_base_data(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit Card",
                    type="CREDIT",
                )
            )
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-1",
                    name="Checking Account",
                    type="BANK",
                )
            )
            session.add_all(
                [
                    Category(
                        id=1,
                        name="Shopping",
                        color="#ef4444",
                        sort_order=1,
                    ),
                    Category(
                        id=2,
                        name="Pets",
                        color="#22c55e",
                        sort_order=2,
                    ),
                    Category(
                        id=3,
                        name="Outros",
                        color="#64748b",
                        sort_order=99,
                    ),
                ]
            )
            session.add(CategoryRule(pluggy_category="Shopping", category_id=1))
            session.add(CategoryRule(pluggy_category="Healthcare", category_id=3))
            session.add(
                DescriptionCategoryRule(
                    pattern="Cobasi Canoas",
                    pattern_normalized=normalize_description("Cobasi Canoas"),
                    category_id=2,
                )
            )
            session.add(
                IgnoredDescriptionRule(
                    pattern="Pagamento recebido",
                    pattern_normalized=normalize_description("Pagamento recebido"),
                )
            )
            session.add_all(
                [
                    Transaction(
                        id="tx-shopping",
                        account_id="credit-1",
                        date=self.current_month_day,
                        amount=Decimal("-100.00"),
                        description="Compra Shopping",
                        category="Shopping",
                    ),
                    Transaction(
                        id="tx-pet",
                        account_id="credit-1",
                        date=self.current_month_day,
                        amount=Decimal("-50.00"),
                        description="Cobasi Canoas",
                        category="Healthcare",
                    ),
                    Transaction(
                        id="tx-invoice-payment",
                        account_id="credit-1",
                        date=self.current_month_day,
                        amount=Decimal("-150.00"),
                        description="Pagamento recebido",
                        category="Credit card payment",
                    ),
                    Transaction(
                        id="tx-future",
                        account_id="credit-1",
                        date=self.next_month_day,
                        amount=Decimal("-75.00"),
                        description="Compra futura",
                        category="Shopping",
                    ),
                    Transaction(
                        id="tx-salary",
                        account_id="bank-1",
                        date=self.current_month_day,
                        amount=Decimal("5000.00"),
                        description="Salario Empresa",
                        category="Salary",
                    ),
                    Transaction(
                        id="tx-interest",
                        account_id="bank-1",
                        date=self.current_month_day,
                        amount=Decimal("0.01"),
                        description="Rendimentos REND PAGO APLIC",
                        category="Proceeds interests and dividends",
                    ),
                    Transaction(
                        id="tx-bank-outflow",
                        account_id="bank-1",
                        date=self.current_month_day,
                        amount=Decimal("-260.00"),
                        description="Pagamento de Pix QR Code",
                        category="Transfers",
                    ),
                ]
            )
            session.commit()

    def test_transactions_default_to_credit_past_non_ignored(self):
        response = self.client.get("/transactions")

        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual({"tx-pet", "tx-shopping"}, {row["id"] for row in rows})
        pet_row = next(row for row in rows if row["id"] == "tx-pet")
        self.assertEqual(pet_row["custom_category_name"], "Pets")
        self.assertFalse(any(row["id"] == "tx-invoice-payment" for row in rows))
        self.assertFalse(any(row["id"] == "tx-salary" for row in rows))
        self.assertFalse(any(row["id"] == "tx-future" for row in rows))

    def test_transactions_can_include_bank_accounts_and_ignored_rows(self):
        response = self.client.get(
            "/transactions",
            params={"account_type": "ALL", "include_ignored": "true"},
        )

        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()}
        self.assertEqual(
            {
                "tx-shopping",
                "tx-pet",
                "tx-invoice-payment",
                "tx-salary",
                "tx-interest",
                "tx-bank-outflow",
            },
            ids,
        )

    def test_stats_use_credit_spend_only_and_track_future_count(self):
        response = self.client.get("/stats")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_spent"], 150.0)
        self.assertEqual(payload["transaction_count"], 2)
        self.assertEqual(payload["future_transaction_count"], 1)
        self.assertEqual(
            {"Shopping": 100.0, "Pets": 50.0},
            {row["name"]: row["total"] for row in payload["categories"]},
        )

    def test_upcoming_groups_future_credit_transactions(self):
        response = self.client.get("/upcoming")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["months"][0]["month"], self.next_month_day.strftime("%Y-%m"))
        self.assertEqual(payload["months"][0]["total"], 75.0)
        self.assertEqual(payload["months"][0]["categories"][0]["name"], "Shopping")

    def test_budget_progress_separates_budgeted_and_unbudgeted_spend(self):
        with Session(self.engine) as session:
            session.add(Budget(category_id=1, monthly_target=Decimal("200.00")))
            session.add(Budget(category_id=2, monthly_target=Decimal("80.00")))
            session.add(
                BudgetOverride(
                    category_id=2,
                    year_month=self.current_month,
                    monthly_target=Decimal("100.00"),
                )
            )
            session.commit()

        response = self.client.get(
            "/budgets/progress",
            params={"year_month": self.current_month},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["target"], 300.0)
        self.assertEqual(payload["summary"]["actual_spent"], 150.0)
        self.assertEqual(payload["summary"]["projected_spent"], 150.0)
        self.assertEqual(payload["summary"]["progress_pct"], 50.0)

        items_by_name = {item["category_name"]: item for item in payload["items"]}
        self.assertEqual(items_by_name["Shopping"]["target_scope"], "default")
        self.assertEqual(items_by_name["Shopping"]["actual_spent"], 100.0)
        self.assertEqual(items_by_name["Pets"]["target_scope"], "month")
        self.assertEqual(items_by_name["Pets"]["target"], 100.0)
        self.assertEqual(items_by_name["Pets"]["actual_spent"], 50.0)

    def test_credit_card_payments_snapshot_uses_invoice_payment_only(self):
        response = self.client.get(
            "/credit-card-payments/monthly",
            params={"months": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 150.0)
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["months"][0]["month"], self.current_month)
        self.assertEqual(payload["months"][0]["transactions"][0]["id"], "tx-invoice-payment")

    def test_bank_income_respects_real_income_exclusion_rules(self):
        with Session(self.engine) as session:
            session.add(
                BankIncomeExclusionRule(
                    pluggy_category="Proceeds interests and dividends"
                )
            )
            session.commit()

        response = self.client.get("/bank-income/monthly", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_income"], 5000.0)
        self.assertEqual(payload["transaction_count"], 1)
        self.assertEqual(payload["months"][0]["transactions"][0]["id"], "tx-salary")

    def test_monthly_balance_combines_income_card_spend_and_invoice_payment(self):
        with Session(self.engine) as session:
            session.add(
                BankIncomeExclusionRule(
                    pluggy_category="Proceeds interests and dividends"
                )
            )
            session.commit()

        response = self.client.get("/monthly-balance", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        self.assertEqual(summary["income"], 5000.0)
        self.assertEqual(summary["card_spend"], 150.0)
        self.assertEqual(summary["invoice_paid"], 150.0)
        self.assertEqual(summary["net_by_purchase_month"], 4850.0)
        self.assertEqual(summary["net_cashflow"], 4850.0)

    def test_rule_endpoints_report_affected_transactions(self):
        response = self.client.post(
            "/category-rules/description",
            json={"pattern": "Compra Shopping", "category_id": 2},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["category_name"], "Pets")
        self.assertEqual(payload["affected_count"], 1)

        response = self.client.post(
            "/bank-income/exclusion-rules",
            json={"pattern": "rendimentos"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pattern_normalized"], "rendimentos")
        self.assertEqual(payload["affected_count"], 1)


if __name__ == "__main__":
    unittest.main()
