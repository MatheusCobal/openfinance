import unittest
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.categorization import normalize_description
from app.database import get_session
from app.main import app
from app.models import (
    Account,
    BankCashflowExclusionRule,
    BankIncomeMonth,
    BankIncomeExclusionRule,
    Budget,
    BudgetOverride,
    Category,
    CategoryRule,
    CreditCardInvoiceMonth,
    DescriptionCategoryRule,
    IgnoredDescriptionRule,
    Item,
    MonthlyBalanceMonth,
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
                        amount=Decimal("50.00"),
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
                        amount=Decimal("75.00"),
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

    def _wipe_credit_seed(self):
        with Session(self.engine) as session:
            for tx_id in ("tx-shopping", "tx-pet", "tx-invoice-payment", "tx-future"):
                tx = session.get(Transaction, tx_id)
                if tx is not None:
                    session.delete(tx)
            session.commit()

    def test_stats_invoice_open_mode_when_no_payment_in_period(self):
        # Last payment was 5 days ago; from then on only the recent purchase
        # counts toward the open invoice.
        self._wipe_credit_seed()
        payment_date = self.today - timedelta(days=5)
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-old-purchase",
                        account_id="credit-1",
                        date=self.today - timedelta(days=20),
                        amount=Decimal("-300.00"),
                        description="Compra antiga",
                        category="Shopping",
                    ),
                    Transaction(
                        id="tx-old-payment",
                        account_id="credit-1",
                        date=payment_date,
                        amount=Decimal("-500.00"),
                        description="Pagamento de fatura",
                        category="Credit card payment",
                    ),
                    Transaction(
                        id="tx-recent-purchase",
                        account_id="credit-1",
                        date=self.today - timedelta(days=1),
                        amount=Decimal("-77.00"),
                        description="Compra recente",
                        category="Shopping",
                    ),
                ]
            )
            session.commit()

        # No from_date, so the period includes the payment 5 days ago →
        # we ARE in 'paid' mode for that, not 'open'. Use a from_date strictly
        # after the payment to force 'open' mode.
        params = {"from_date": (payment_date + timedelta(days=1)).isoformat()}
        payload = self.client.get("/stats", params=params).json()

        self.assertEqual(payload["invoice_mode"], "open")
        self.assertEqual(payload["invoice_total"], 77.0)
        self.assertEqual(payload["invoice_count"], 1)
        self.assertEqual(payload["invoice_since"], payment_date.isoformat())

    def test_stats_invoice_paid_mode_when_payment_in_period(self):
        # Period contains a closed cycle — show the paid amount, not an open
        # invoice for the same window.
        self._wipe_credit_seed()
        payment_date = self.today - timedelta(days=2)
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-payment-in-period",
                        account_id="credit-1",
                        date=payment_date,
                        amount=Decimal("-1620.50"),
                        description="Pagamento de fatura",
                        category="Credit card payment",
                    ),
                    Transaction(
                        id="tx-purchase-after-payment",
                        account_id="credit-1",
                        date=self.today,
                        amount=Decimal("-99.00"),
                        description="Compra hoje",
                        category="Shopping",
                    ),
                ]
            )
            session.commit()

        params = {"from_date": (payment_date - timedelta(days=1)).isoformat()}
        payload = self.client.get("/stats", params=params).json()

        self.assertEqual(payload["invoice_mode"], "paid")
        self.assertEqual(payload["invoice_total"], 1620.5)
        self.assertEqual(payload["invoice_count"], 1)
        self.assertEqual(payload["invoice_paid_dates"], [payment_date.isoformat()])

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
        # The R$ 260 PIX outflow (tx-bank-outflow) falls into "Outros"
        # — no budget — so it must surface as unbudgeted spend, not as
        # silent invisible spending like before.
        self.assertEqual(payload["summary"]["unbudgeted_actual_spent"], 260.0)
        self.assertEqual(items_by_name["Outros"]["actual_spent"], 260.0)

    def test_budget_progress_includes_bank_pix_in_budgeted_category(self):
        # PIX outflows tagged with a category that has a budget must count
        # toward that budget — historically only CREDIT spend was tracked
        # and PIX was invisible.
        with Session(self.engine) as session:
            session.add(Budget(category_id=1, monthly_target=Decimal("500.00")))
            # PIX to a store that maps via DescriptionCategoryRule to "Pets"
            session.add(
                Transaction(
                    id="tx-pix-cobasi",
                    account_id="bank-1",
                    date=self.current_month_day,
                    amount=Decimal("-120.00"),
                    description="Cobasi Canoas PIX",
                    category="Transfers",
                )
            )
            session.add(Budget(category_id=2, monthly_target=Decimal("300.00")))
            session.commit()

        response = self.client.get(
            "/budgets/progress",
            params={"year_month": self.current_month},
        )

        self.assertEqual(response.status_code, 200)
        items = {item["category_name"]: item for item in response.json()["items"]}
        # Pets had R$ 50 on credit + R$ 120 via PIX = R$ 170
        self.assertEqual(items["Pets"]["actual_spent"], 170.0)

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
            session.add(BankIncomeExclusionRule(pluggy_category="Proceeds interests and dividends"))
            session.commit()

        response = self.client.get("/bank-income/monthly", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_income"], 5000.0)
        self.assertEqual(payload["transaction_count"], 1)
        self.assertEqual(payload["months"][0]["transactions"][0]["id"], "tx-salary")

    def test_monthly_balance_combines_income_card_spend_and_invoice_payment(self):
        with Session(self.engine) as session:
            session.add(BankIncomeExclusionRule(pluggy_category="Proceeds interests and dividends"))
            session.commit()

        response = self.client.get("/monthly-balance", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        self.assertEqual(summary["income"], 5000.0)
        self.assertEqual(summary["card_spend"], 150.0)
        self.assertEqual(summary["invoice_paid"], 150.0)
        self.assertEqual(summary["net_by_purchase_month"], 4850.0)
        self.assertEqual(summary["net_cashflow"], 4850.0)

    def test_read_endpoints_do_not_create_snapshot_rows(self):
        endpoints = [
            ("/bank-income/monthly", {"months": 1}),
            ("/monthly-balance", {"months": 1}),
            ("/expected-income/forecast", {"year_month": self.current_month}),
            ("/credit-card-payments/history", {}),
            ("/bank-income/history", {}),
            ("/monthly-balance/history", {}),
        ]

        for path, params in endpoints:
            with self.subTest(path=path):
                response = self.client.get(path, params=params)
                self.assertEqual(response.status_code, 200)

        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BankIncomeMonth)).all(), [])
            self.assertEqual(session.exec(select(CreditCardInvoiceMonth)).all(), [])
            self.assertEqual(session.exec(select(MonthlyBalanceMonth)).all(), [])

    def test_bank_cashflow_includes_ignored_and_respects_cashflow_rules(self):
        response = self.client.get("/bank-cashflow/monthly", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        month = payload["months"][0]
        self.assertEqual(month["income"], 5000.01)
        self.assertEqual(month["outflow"], 260.0)
        self.assertEqual(month["income_count"], 2)
        self.assertEqual(month["outflow_count"], 1)
        self.assertEqual(
            {"tx-salary", "tx-interest", "tx-bank-outflow"},
            {tx["id"] for tx in month["transactions"]},
        )

        with Session(self.engine) as session:
            session.add(
                BankCashflowExclusionRule(
                    direction="IN",
                    pluggy_category="Proceeds interests and dividends",
                )
            )
            session.commit()

        response = self.client.get("/bank-cashflow/monthly", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        month = response.json()["months"][0]
        self.assertEqual(month["income"], 5000.0)
        self.assertEqual(month["income_count"], 1)
        self.assertEqual(
            {"tx-salary", "tx-bank-outflow"},
            {tx["id"] for tx in month["transactions"]},
        )

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

        response = self.client.post(
            "/bank-cashflow/exclusion-rules",
            json={"direction": "OUT", "pattern": "Pix QR Code"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["direction"], "OUT")
        self.assertEqual(payload["pattern_normalized"], "pix qr code")
        self.assertEqual(payload["affected_count"], 1)

    def test_description_rule_suggestions_group_repeated_unruled_descriptions(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-padaria-1",
                        account_id="credit-1",
                        date=self.current_month_day,
                        amount=Decimal("-10.00"),
                        description="Padaria Centro",
                        category="Food",
                    ),
                    Transaction(
                        id="tx-padaria-2",
                        account_id="credit-1",
                        date=self.current_month_day,
                        amount=Decimal("-15.00"),
                        description="Padaria Centro",
                        category="Food",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/category-rules/description/suggestions",
            params={"months": 1, "min_count": 2, "limit": 5},
        )

        self.assertEqual(response.status_code, 200)
        suggestions = response.json()["suggestions"]
        padaria = next(
            item
            for item in suggestions
            if item["pattern_normalized"] == normalize_description("Padaria Centro")
        )
        self.assertEqual(padaria["transaction_count"], 2)
        self.assertEqual(padaria["total"], 25.0)
        self.assertEqual(padaria["current_category_name"], "Outros")
        self.assertNotIn(
            normalize_description("Cobasi Canoas"),
            {item["pattern_normalized"] for item in suggestions},
        )

    def test_rule_upserts_are_idempotent(self):
        first_response = self.client.post(
            "/category-rules/description",
            json={"pattern": "Cobasi Canoas", "category_id": 1},
        )
        second_response = self.client.post(
            "/category-rules/description",
            json={"pattern": "  cobasi   canoas  ", "category_id": 2},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["id"], second_response.json()["id"])
        self.assertEqual(second_response.json()["category_name"], "Pets")

        first_response = self.client.post(
            "/transaction-ignore-rules/description",
            json={"pattern": "Pagamento recebido"},
        )
        second_response = self.client.post(
            "/transaction-ignore-rules/description",
            json={"pattern": " pagamento   recebido "},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["id"], second_response.json()["id"])

        first_response = self.client.post(
            "/bank-income/exclusion-rules",
            json={"pattern": "rendimentos"},
        )
        second_response = self.client.post(
            "/bank-income/exclusion-rules",
            json={"pattern": " RENDIMENTOS "},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["id"], second_response.json()["id"])

        first_response = self.client.post(
            "/bank-cashflow/exclusion-rules",
            json={"direction": "IN", "pattern": "rendimentos"},
        )
        second_response = self.client.post(
            "/bank-cashflow/exclusion-rules",
            json={"direction": "in", "pattern": " RENDIMENTOS "},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["id"], second_response.json()["id"])

        with Session(self.engine) as session:
            description_rules = session.exec(
                select(DescriptionCategoryRule).where(
                    DescriptionCategoryRule.pattern_normalized
                    == normalize_description("Cobasi Canoas")
                )
            ).all()
            ignored_rules = session.exec(
                select(IgnoredDescriptionRule).where(
                    IgnoredDescriptionRule.pattern_normalized
                    == normalize_description("Pagamento recebido")
                )
            ).all()
            bank_rules = session.exec(
                select(BankIncomeExclusionRule).where(
                    BankIncomeExclusionRule.pattern_normalized
                    == normalize_description("rendimentos")
                )
            ).all()
            cashflow_rules = session.exec(
                select(BankCashflowExclusionRule).where(
                    BankCashflowExclusionRule.pattern_normalized
                    == normalize_description("rendimentos")
                )
            ).all()

        self.assertEqual(len(description_rules), 1)
        self.assertEqual(len(ignored_rules), 1)
        self.assertEqual(len(bank_rules), 1)
        self.assertEqual(len(cashflow_rules), 1)

    def test_http_validation_rejects_invalid_transaction_account_type(self):
        response = self.client.get(
            "/transactions",
            params={"account_type": "INVESTMENT"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "account_type must be CREDIT, BANK or ALL")

    def test_http_validation_rejects_invalid_month_windows(self):
        endpoints = [
            "/credit-card-payments/monthly",
            "/bank-income/monthly",
            "/bank-cashflow/monthly",
            "/monthly-balance",
        ]

        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint, params={"months": 0})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"], "months must be between 1 and 24")

                response = self.client.get(endpoint, params={"months": 25})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"], "months must be between 1 and 24")

    def test_http_validation_rejects_invalid_budget_inputs(self):
        response = self.client.get(
            "/budgets/progress",
            params={"year_month": "2026-13"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "year_month must be a valid calendar month")

        response = self.client.put(
            "/budgets/1",
            json={"monthly_target": "0"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "monthly_target must be > 0")

        response = self.client.put(
            "/budgets/999",
            json={"monthly_target": "100"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "category not found")

        response = self.client.put(
            "/budgets/1/months/not-a-month",
            json={"monthly_target": "100"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "year_month must use YYYY-MM format")

    def test_http_validation_rejects_invalid_rule_payloads(self):
        response = self.client.post(
            "/category-rules/description",
            json={"pattern": "   ", "category_id": 1},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "pattern must not be empty")

        response = self.client.post(
            "/category-rules/description",
            json={"pattern": "Cobasi", "category_id": 999},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "category not found")

        response = self.client.post(
            "/transaction-ignore-rules/description",
            json={"pattern": "   "},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "pattern must not be empty")

        response = self.client.post(
            "/bank-income/exclusion-rules",
            json={},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Provide exactly one of pluggy_category or pattern",
        )

        response = self.client.post(
            "/bank-income/exclusion-rules",
            json={"pluggy_category": "Salary", "pattern": "salary"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Provide exactly one of pluggy_category or pattern",
        )


if __name__ == "__main__":
    unittest.main()
