import unittest
from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import (
    Account,
    Category,
    CategoryRule,
    CreditCardBill,
    ExpectedIncome,
    IgnoredDescriptionRule,
    Item,
    Transaction,
)
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.current_card_invoice import current_card_invoice_summary
from app.services.planning import planning_month_summary

LEGACY_CATEGORY_TEST_REMOVED = "10D-A removed current-invoice category cards; replace in 10D-B"


class CurrentCardInvoiceTest(unittest.TestCase):
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

    def _add_item(self, session, item_id="item-1", active=True):
        session.add(
            Item(
                id=item_id,
                connector_id=200,
                status="UPDATED",
                is_active=active,
            )
        )

    def _add_credit_account(
        self,
        session,
        *,
        account_id="credit-1",
        item_id="item-1",
        balance=Decimal("1000"),
        due_date=date(2026, 6, 8),
        active=True,
    ):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="LATAM PASS ITAU MASTERCARD BLACK",
                type="CREDIT",
                balance=Decimal(balance),
                credit_balance_due_date=due_date,
                balance_updated_at=datetime(2026, 6, 8, 18, 37),
                is_active=active,
            )
        )

    def _add_bank_account(self, session, account_id="bank-1", item_id="item-1"):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Conta corrente",
                type="BANK",
                balance=Decimal("5000"),
            )
        )

    def _add_bill(
        self,
        session,
        *,
        bill_id="bill-1",
        account_id="credit-1",
        due_date=date(2026, 6, 8),
        total=Decimal("17131.28"),
    ):
        session.add(
            CreditCardBill(
                id=bill_id,
                account_id=account_id,
                due_date=due_date,
                total_amount=Decimal(total),
            )
        )

    def test_raw_balance_without_previous_bill_uses_account_balance(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 1000.0)
        self.assertEqual(summary["source"], "account_balance")

    def test_raw_balance_with_previous_bill_loaded_subtracts_closed_bill(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 11488.32)
        self.assertEqual(summary["source"], "adjusted_account_balance")
        self.assertEqual(summary["cards"][0]["adjustments"][0]["type"], "subtract_closed_bill")

    def test_raw_balance_below_latest_bill_does_not_go_negative(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            self._add_bill(session, total=Decimal("17131.28"))
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 1000.0)
        self.assertEqual(summary["source"], "account_balance")
        self.assertEqual(summary["cards"][0]["adjustments"], [])

    def test_future_reliable_bill_does_not_subtract_previous_bill(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(
                session,
                balance=Decimal("12000"),
                due_date=date(2026, 7, 8),
            )
            self._add_bill(session, bill_id="bill-jun", due_date=date(2026, 6, 8))
            self._add_bill(
                session,
                bill_id="bill-jul",
                due_date=date(2026, 7, 8),
                total=Decimal("12000"),
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 12000.0)
        self.assertEqual(summary["source"], "account_balance")
        self.assertEqual(summary["cards"][0]["next_bill_id"], "bill-jul")

    def test_invoice_payment_near_due_date_raises_confidence_to_high(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(
                Transaction(
                    id="payment-1",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-17131.28"),
                    description="Pagamento recebido",
                    category="Card payments",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["confidence"], "high")
        self.assertEqual(
            summary["cards"][0]["matched_payment_transactions"][0]["id"],
            "payment-1",
        )

    def test_bank_invoice_payment_near_due_date_also_raises_confidence(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bank_account(session)
            self._add_bill(session)
            session.add(
                Transaction(
                    id="bank-payment-1",
                    account_id="bank-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-17131.28"),
                    description="Pagamento de boleto Itau Unibanco",
                    category="Transfers",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["confidence"], "high")
        self.assertEqual(
            summary["cards"][0]["matched_payment_transactions"][0]["id"],
            "bank-payment-1",
        )

    def test_duplicate_payment_and_refund_transactions_are_ignored(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(
                Transaction(
                    id="dup-payment",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-17131.28"),
                    description="Pagamento recebido",
                    category="Card payments",
                    is_duplicate=True,
                )
            )
            session.add(
                Transaction(
                    id="dup-refund",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-873"),
                    description="CANC PARCELA SEM J",
                    category="Electronics",
                    is_duplicate=True,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["confidence"], "medium")
        self.assertEqual(summary["cards"][0]["matched_payment_transactions"], [])
        self.assertEqual(summary["possible_refund_transactions"], [])

    def test_inactive_accounts_and_items_do_not_enter_calculation(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_item(session, item_id="item-inactive", active=False)
            self._add_credit_account(session, balance=Decimal("100"))
            self._add_credit_account(
                session,
                account_id="credit-inactive",
                balance=Decimal("900"),
                active=False,
            )
            self._add_credit_account(
                session,
                account_id="credit-item-inactive",
                item_id="item-inactive",
                balance=Decimal("500"),
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 100.0)
        self.assertEqual(summary["account_count"], 1)
        self.assertEqual(summary["cards"][0]["account_id"], "credit-1")

    def test_negative_credit_transaction_is_reported_as_possible_refund_only(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(
                Transaction(
                    id="refund-1",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-873"),
                    description="CANC PARCELA SEM J",
                    category="Electronics",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["amount"], 11488.32)
        self.assertEqual(summary["possible_refunds_total"], -873.0)
        self.assertEqual(summary["possible_refund_transactions"][0]["id"], "refund-1")
        self.assertTrue(summary["source_detail"]["refunds_are_diagnostic_only"])

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_categories_use_current_invoice_transactions_not_future_planning_month(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(Category(id=1, name="Mercado", color="#22c55e", sort_order=1))
            session.add(CategoryRule(pluggy_category="Food", category_id=1))
            session.add(
                Transaction(
                    id="market-1",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("100.25"),
                    description="Supermercado",
                    category="Food",
                )
            )
            session.add(
                Transaction(
                    id="market-2",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("50.75"),
                    description="Padaria",
                    category="Food",
                )
            )
            session.add(
                Transaction(
                    id="future-market",
                    account_id="credit-1",
                    date=date(2026, 7, 5),
                    amount=Decimal("999"),
                    description="Compra futura",
                    category="Food",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["category_total"], 151.0)
        self.assertEqual(summary["category_count"], 2)
        self.assertEqual(len(summary["categories"]), 1)
        self.assertEqual(summary["categories"][0]["name"], "Mercado")
        self.assertEqual(summary["categories"][0]["count"], 2)
        self.assertEqual(
            summary["categories"][0]["transactions"][0]["custom_category_name"], "Mercado"
        )

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_categories_skip_payments_duplicates_refunds_and_latest_bill_rows(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(Category(id=1, name="Mercado", color="#22c55e", sort_order=1))
            session.add(CategoryRule(pluggy_category="Food", category_id=1))
            rows = [
                Transaction(
                    id="valid-current",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("100"),
                    description="Supermercado",
                    category="Food",
                ),
                Transaction(
                    id="latest-bill-row",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("900"),
                    description="Compra fatura anterior",
                    category="Food",
                    bill_id="bill-1",
                ),
                Transaction(
                    id="payment-row",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-17131.28"),
                    description="Pagamento recebido",
                    category="Card payments",
                ),
                Transaction(
                    id="duplicate-row",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("500"),
                    description="Compra duplicada",
                    category="Food",
                    is_duplicate=True,
                ),
                # Excluded by text pattern ("canc parcela")
                Transaction(
                    id="refund-text-row",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-80"),
                    description="CANC PARCELA SEM J",
                    category="Food",
                ),
                # Excluded by negative amount alone — no text pattern matches
                Transaction(
                    id="refund-negative-row",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("-52.50"),
                    description="Reducao Mensalidade Plano",
                    category="Food",
                ),
            ]
            session.add_all(rows)
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        self.assertEqual(summary["category_total"], 100.0)
        self.assertEqual(summary["category_count"], 1)
        self.assertEqual(
            [tx["id"] for tx in summary["categories"][0]["transactions"]],
            ["valid-current"],
        )
        # Both refund rows must be absent from categories
        all_cat_ids = [tx["id"] for cat in summary["categories"] for tx in cat["transactions"]]
        self.assertNotIn("refund-text-row", all_cat_ids)
        self.assertNotIn("refund-negative-row", all_cat_ids)

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_negative_amount_without_text_pattern_is_excluded_from_categories(self):
        """A credit-card transaction with amount < 0 and no refund keyword in its
        description must not appear in categories or contribute to category_total,
        even though _looks_like_refund_text() returns False for it."""
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            session.add(Category(id=1, name="Outros", color="#94a3b8", sort_order=99))
            rows = [
                # Normal purchase — must appear in categories
                Transaction(
                    id="purchase-1",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("200"),
                    description="Loja XYZ",
                    category="Shopping",
                ),
                # Negative amount, neutral description — the bug that was reported
                Transaction(
                    id="credit-neutral-desc",
                    account_id="credit-1",
                    date=date(2026, 6, 6),
                    amount=Decimal("-52.50"),
                    description="Reducao Mensalidade Plano",
                    category="Services",
                ),
            ]
            session.add_all(rows)
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        all_cat_ids = [tx["id"] for cat in summary["categories"] for tx in cat["transactions"]]
        self.assertIn("purchase-1", all_cat_ids, "normal purchase must be in categories")
        self.assertNotIn(
            "credit-neutral-desc",
            all_cat_ids,
            "negative-amount tx must be excluded from categories even without a refund keyword",
        )
        # category_total must only count the positive purchase
        self.assertAlmostEqual(summary["category_total"], 200.0, places=2)
        self.assertEqual(summary["category_count"], 1)
        # The negative tx must surface in possible_refund_transactions
        refund_ids = [tx["id"] for tx in summary["possible_refund_transactions"]]
        self.assertIn(
            "credit-neutral-desc",
            refund_ids,
            "negative-amount tx must appear in possible_refund_transactions",
        )

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_endpoint_returns_current_invoice_summary(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            session.add(Category(id=1, name="Mercado", color="#22c55e", sort_order=1))
            session.add(CategoryRule(pluggy_category="Food", category_id=1))
            session.add(
                Transaction(
                    id="market-1",
                    account_id="credit-1",
                    date=date.today(),
                    amount=Decimal("100"),
                    description="Supermercado",
                    category="Food",
                )
            )
            session.commit()

        response = self.client.get("/credit-card/current-invoice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["amount"], 1000.0)
        self.assertEqual(response.json()["category_total"], 100.0)
        self.assertEqual(response.json()["categories"][0]["name"], "Mercado")

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_ignored_description_rule_excludes_transaction_from_categories(self):
        """IgnoredDescriptionRule must suppress matching transactions from
        categories, category_total, category_count, and categories[].transactions."""
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            session.add(Category(id=1, name="Digital", color="#6366f1", sort_order=1))
            session.add(CategoryRule(pluggy_category="Digital services", category_id=1))
            # Ignored subscription instalment — pattern must match this
            session.add(
                Transaction(
                    id="ignored-sub",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("103.11"),
                    description="IG*edzkaiserplSoro02/12",
                    category="Digital services",
                )
            )
            # Legitimate digital purchase — must NOT be excluded
            session.add(
                Transaction(
                    id="legit-digital",
                    account_id="credit-1",
                    date=date(2026, 6, 6),
                    amount=Decimal("49.90"),
                    description="Netflix Subscription",
                    category="Digital services",
                )
            )
            # Ignore rule stored in the database (configurable, not hardcoded)
            session.add(
                IgnoredDescriptionRule(
                    pattern="edzkaiserplSoro",
                    pattern_normalized="edzkaiserplsoro",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        category_tx_ids = [tx["id"] for cat in summary["categories"] for tx in cat["transactions"]]
        self.assertNotIn(
            "ignored-sub",
            category_tx_ids,
            "ignored tx must not appear in categories[].transactions",
        )
        self.assertIn("legit-digital", category_tx_ids, "legitimate tx must still appear")
        self.assertEqual(summary["category_count"], 1, "only the legitimate tx should be counted")
        self.assertAlmostEqual(summary["category_total"], 49.90, places=2)

    @unittest.skip(LEGACY_CATEGORY_TEST_REMOVED)
    def test_reconciliation_field_present_and_correct(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            self._add_bill(session)
            session.add(Category(id=1, name="Mercado", color="#22c55e", sort_order=1))
            session.add(CategoryRule(pluggy_category="Food", category_id=1))
            session.add(
                Transaction(
                    id="purchase-1",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("500"),
                    description="Supermercado",
                    category="Food",
                )
            )
            session.add(
                Transaction(
                    id="refund-1",
                    account_id="credit-1",
                    date=date(2026, 6, 6),
                    amount=Decimal("-100"),
                    description="CANC PARCELA SEM J",
                    category="Food",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        rec = summary["reconciliation"]
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(rec["amount"], summary["amount"], places=2)
        self.assertAlmostEqual(rec["category_total"], summary["category_total"], places=2)
        self.assertAlmostEqual(rec["refund_total"], summary["possible_refunds_total"], places=2)
        self.assertAlmostEqual(
            rec["refund_abs_total"], abs(summary["possible_refunds_total"]), places=2
        )
        self.assertAlmostEqual(
            rec["amount_minus_category_total"],
            summary["amount"] - summary["category_total"],
            places=2,
        )
        self.assertFalse(rec["refunds_affect_amount"])
        self.assertTrue(rec["refunds_are_diagnostic_only"])
        self.assertIn("source_label", rec)

    def test_future_planning_month_can_still_use_scheduled_installments(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("0"), due_date=None)
            session.add(
                Transaction(
                    id="future-installment",
                    account_id="credit-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("7993.58"),
                    description="Parcela viagem 03/12",
                    category="Travel",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = planning_invoice_for_month(
                session,
                "2026-07",
                today=date(2026, 6, 15),
            )

        self.assertEqual(summary["source"], "scheduled_installments")
        self.assertEqual(summary["amount"], 7993.58)

    def test_dashboard_capacity_uses_adjusted_current_invoice_when_planning_differs(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(
                session,
                balance=Decimal("28619.60"),
                due_date=date(2026, 6, 8),
            )
            self._add_bill(
                session,
                bill_id="bill-jun",
                due_date=date(2026, 6, 8),
                total=Decimal("17131.28"),
            )
            self._add_bill(
                session,
                bill_id="bill-jul",
                due_date=date(2026, 7, 8),
                total=Decimal("17131.28"),
            )
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("20000"),
                    expected_day=5,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            planning = planning_month_summary(
                session,
                "2026-07",
                today=date(2026, 6, 8),
            )
            current_invoice = current_card_invoice_summary(
                session,
                today=date(2026, 6, 8),
            )

        planning_invoice_amount = planning["credit_card_invoice"]["amount"]
        current_invoice_amount = current_invoice["amount"]
        dashboard_available = (
            planning["income"]["expected"]
            - planning["fixed_costs"]["planned"]
            - planning["variable_budgets"]["planned"]
            - current_invoice_amount
        )

        self.assertEqual(planning_invoice_amount, 17131.28)
        self.assertEqual(current_invoice_amount, 11488.32)
        self.assertNotEqual(planning_invoice_amount, current_invoice_amount)
        self.assertNotEqual(
            dashboard_available,
            planning["capacity"]["available_to_spend"],
        )
        self.assertAlmostEqual(dashboard_available, 8511.68, places=2)


if __name__ == "__main__":
    unittest.main()
