import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

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
    CreditCardInvoiceMonth,
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
            ("/credit-card-payments/monthly", {"months": 1}),
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

    def test_history_get_endpoints_do_not_call_snapshot_refresh(self):
        endpoints = [
            ("/credit-card-payments/history", {}),
            ("/bank-income/history", {}),
            ("/monthly-balance", {"months": 1}),
            ("/monthly-balance/history", {}),
        ]

        with (
            patch("app.services.snapshots.refresh_credit_card_invoice_snapshots") as credit_refresh,
            patch("app.services.snapshots.refresh_bank_income_snapshots") as income_refresh,
            patch("app.services.snapshots.refresh_monthly_balance_snapshots") as balance_refresh,
        ):
            for path, params in endpoints:
                with self.subTest(path=path):
                    response = self.client.get(path, params=params)
                    self.assertEqual(response.status_code, 200)

        credit_refresh.assert_not_called()
        income_refresh.assert_not_called()
        balance_refresh.assert_not_called()

    def test_history_snapshots_refresh_requires_post(self):
        response = self.client.get("/history/snapshots/refresh", params={"months": 1})
        self.assertEqual(response.status_code, 405)

    def test_history_snapshots_refresh_backs_up_before_refresh(self):
        calls = []
        with (
            patch(
                "app.routes.history.backup_sqlite_database",
                side_effect=lambda *args, **kwargs: calls.append("backup"),
            ) as backup,
            patch(
                "app.routes.history.refresh_monthly_balance_snapshots",
                side_effect=lambda *args, **kwargs: calls.append("refresh") or (1, 2, 3),
            ) as refresh,
        ):
            response = self.client.post("/history/snapshots/refresh", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["refreshed"]["bank_income"], 1)
        self.assertEqual(response.json()["refreshed"]["credit_card_invoice"], 2)
        self.assertEqual(response.json()["refreshed"]["monthly_balance"], 3)
        backup.assert_called_once()
        self.assertEqual(backup.call_args.args[1], "snapshot-refresh")
        refresh.assert_called_once()
        self.assertEqual(calls, ["backup", "refresh"])

    def test_history_snapshots_refresh_post_creates_snapshots(self):
        response = self.client.post("/history/snapshots/refresh", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            set(payload["refreshed"].keys()),
            {"bank_income", "credit_card_invoice", "monthly_balance"},
        )
        self.assertGreaterEqual(payload["refreshed"]["bank_income"], 1)
        self.assertGreaterEqual(payload["refreshed"]["credit_card_invoice"], 1)
        self.assertGreaterEqual(payload["refreshed"]["monthly_balance"], 1)

        with Session(self.engine) as session:
            bank_income = session.get(BankIncomeMonth, self.current_month)
            invoice = session.get(CreditCardInvoiceMonth, self.current_month)
            balance = session.get(MonthlyBalanceMonth, self.current_month)

        self.assertIsNotNone(bank_income)
        self.assertIsNotNone(invoice)
        self.assertIsNotNone(balance)
        self.assertAlmostEqual(float(bank_income.total), 5000.01, places=2)
        self.assertAlmostEqual(float(invoice.total), 150.0, places=2)
        self.assertAlmostEqual(float(balance.invoice_paid), 150.0, places=2)

    def test_bank_cashflow_includes_all_bank_movements_and_ignores_cashflow_rules(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-boleto-outflow",
                        account_id="bank-1",
                        date=self.current_month_day,
                        amount=Decimal("-1200.00"),
                        description="Aluguel pago por boleto",
                        category="Transfer - Bank Slip",
                    ),
                    Transaction(
                        id="tx-boleto-inflow",
                        account_id="bank-1",
                        date=self.current_month_day,
                        amount=Decimal("500.00"),
                        description="Boleto recebido",
                        category="Transfer - Bank Slip",
                    ),
                ]
            )
            session.commit()

        response = self.client.get("/bank-cashflow/monthly", params={"months": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "raw_bank_transactions")
        month = payload["months"][0]
        self.assertEqual(month["income"], 5500.01)
        self.assertEqual(month["outflow"], 1460.0)
        self.assertEqual(month["income_count"], 3)
        self.assertEqual(month["outflow_count"], 2)
        self.assertEqual(
            {
                "tx-salary",
                "tx-interest",
                "tx-bank-outflow",
                "tx-boleto-outflow",
                "tx-boleto-inflow",
            },
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
        self.assertEqual(month["income"], 5500.01)
        self.assertEqual(month["outflow"], 1460.0)
        self.assertEqual(month["income_count"], 3)
        self.assertEqual(month["outflow_count"], 2)
        self.assertEqual(
            {
                "tx-salary",
                "tx-interest",
                "tx-bank-outflow",
                "tx-boleto-outflow",
                "tx-boleto-inflow",
            },
            {tx["id"] for tx in month["transactions"]},
        )

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

if __name__ == "__main__":
    unittest.main()
