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
    CreditCardBill,
    ExpectedIncome,
    Item,
    Transaction,
)
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.current_card_invoice import current_card_invoice_summary
from app.services.planning import planning_month_summary


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

    def test_invoice_payment_diagnostic_is_not_exposed(self):
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

        self.assertEqual(summary["confidence"], "medium")
        self.assertNotIn("matched_payment_transactions", summary["cards"][0])
        self.assertNotIn("possible_refunds_total", summary)
        self.assertNotIn("possible_refund_transactions", summary)

    def test_bank_invoice_payment_diagnostic_is_not_exposed(self):
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

        self.assertEqual(summary["confidence"], "medium")
        self.assertNotIn("matched_payment_transactions", summary["cards"][0])

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
        self.assertNotIn("matched_payment_transactions", summary["cards"][0])
        self.assertNotIn("possible_refund_transactions", summary)

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

    def test_negative_credit_transaction_diagnostic_is_not_exposed(self):
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
        self.assertNotIn("possible_refunds_total", summary)
        self.assertNotIn("possible_refund_transactions", summary)
        self.assertNotIn("refund_abs_total", summary["reconciliation"])

    def test_current_invoice_categories_use_credit_category_resolver(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1000"))
            session.add(
                Transaction(
                    id="shopping-as-pet",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("199.90"),
                    description="Compra ajustada manualmente",
                    category="Shopping",
                    pluggy_raw_category="Shopping",
                    internal_category="Pet",
                    cashflow_type="expense",
                    classification_source="manual_override",
                    classification_confidence="high",
                    classification_rule_key="manual_override",
                    is_user_overridden=True,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 8))

        category = next(item for item in summary["categories"] if item["name"] == "Outros")
        self.assertEqual(category["name"], "Outros")
        self.assertEqual(category["effective_category"], "Outros")
        self.assertEqual(category["transactions"][0]["internal_category"], "Pet")
        self.assertEqual(category["transactions"][0]["effective_category"], "Outros")

    def test_categories_include_next_invoice_installments_and_reconcile_to_balance(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("1200"))
            session.add(
                Transaction(
                    id="current-purchase",
                    account_id="credit-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("100"),
                    description="Compra atual",
                    category="Groceries",
                )
            )
            session.add(
                Transaction(
                    id="next-invoice-installment",
                    account_id="credit-1",
                    date=date(2026, 7, 6),
                    amount=Decimal("300"),
                    description="Parcela futura 02/06",
                    category="Shopping",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 18))

        self.assertEqual(summary["amount"], 1200.0)
        self.assertEqual(summary["reconciliation"]["identified_category_total"], 400.0)
        self.assertEqual(summary["reconciliation"]["unreconciled_amount"], 800.0)
        self.assertEqual(summary["reconciliation"]["amount_minus_category_total"], 0.0)
        self.assertEqual(sum(item["total"] for item in summary["categories"]), 1200.0)
        unreconciled = next(
            item
            for item in summary["categories"]
            if item["source"] == "account_balance_reconciliation"
        )
        self.assertEqual(unreconciled["total"], 800.0)
        self.assertEqual(
            {tx["id"] for tx in summary["raw_purchase_transactions"]},
            {"current-purchase", "next-invoice-installment"},
        )
        self.assertEqual(
            [tx["id"] for tx in summary["recent_purchase_transactions"]],
            ["current-purchase"],
        )

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

    def _seed_vigente_scenario(self, session):
        """Mirror the real 11-A bug: stale due date (June), closed June bill
        still inside Account.balance, no official July bill, and July
        future-dated installments that previously fed scheduled_installments."""
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
        session.add(
            Transaction(
                id="future-installment-jul",
                account_id="credit-1",
                date=date(2026, 7, 10),
                amount=Decimal("7993.58"),
                description="Parcela viagem 03/12",
                category="Travel",
            )
        )
        session.commit()

    def test_vigente_planning_month_uses_dashboard_current_invoice(self):
        """Planning for the vigente month must show the same current invoice
        as the Dashboard instead of the smaller scheduled_installments sum."""
        with Session(self.engine) as session:
            self._seed_vigente_scenario(session)

        with Session(self.engine) as session:
            planning = planning_invoice_for_month(
                session,
                "2026-07",
                today=date(2026, 6, 10),
            )
            dashboard = current_card_invoice_summary(
                session,
                today=date(2026, 6, 10),
            )

        self.assertEqual(planning["source"], "dashboard_current_invoice")
        self.assertEqual(planning["amount"], dashboard["amount"])
        self.assertEqual(planning["amount"], 11488.32)
        self.assertNotEqual(planning["amount"], 7993.58)

    def test_vigente_dashboard_tier_only_applies_to_vigente_month(self):
        """A future month beyond the vigente one keeps the existing tiers
        (scheduled_installments here), so months further out are unchanged."""
        with Session(self.engine) as session:
            self._seed_vigente_scenario(session)
            session.add(
                Transaction(
                    id="future-installment-aug",
                    account_id="credit-1",
                    date=date(2026, 8, 10),
                    amount=Decimal("500.00"),
                    description="Parcela viagem 04/12",
                    category="Travel",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            august = planning_invoice_for_month(
                session,
                "2026-08",
                today=date(2026, 6, 10),
            )

        self.assertEqual(august["source"], "scheduled_installments")
        self.assertEqual(august["amount"], 500.0)

    def test_upcoming_summary_next_invoice_matches_dashboard(self):
        """Upcoming ("Próximos") exposes next_invoice with the same value as
        the Dashboard current invoice, not the stale installments-only sum.
        The vigente month row must use that same value too."""
        from app.services.transaction_reports import upcoming_summary

        with Session(self.engine) as session:
            self._seed_vigente_scenario(session)

        with Session(self.engine) as session:
            summary = upcoming_summary(session, today=date(2026, 6, 10))
            dashboard = current_card_invoice_summary(
                session,
                today=date(2026, 6, 10),
            )

        self.assertEqual(summary["next_invoice"]["year_month"], "2026-07")
        self.assertEqual(summary["next_invoice"]["amount"], dashboard["amount"])
        self.assertEqual(summary["next_invoice"]["amount"], 11488.32)
        self.assertEqual(summary["next_invoice"]["source"], "dashboard_current_invoice")
        self.assertEqual(summary["months"][0]["month"], "2026-07")
        self.assertEqual(summary["months"][0]["total"], 11488.32)
        self.assertEqual(summary["months"][0]["invoice_total"], 11488.32)
        self.assertEqual(summary["months"][0]["scheduled_total"], 7993.58)
        self.assertEqual(summary["months"][0]["invoice_source"], "dashboard_current_invoice")
        self.assertTrue(summary["months"][0]["is_current_invoice"])
        self.assertEqual(summary["months"][0]["categories"][0]["name"], "Lazer / Viagem")

    def test_vigente_spending_capacity_uses_dashboard_invoice(self):
        """Spending capacity for the vigente month subtracts the Dashboard
        invoice amount as the future card obligation."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            self._seed_vigente_scenario(session)

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session,
                "2026-07",
                today=date(2026, 6, 10),
            )

        self.assertEqual(capacity["card_invoice_source"], "dashboard_current_invoice")
        self.assertEqual(capacity["future_card_obligation_source"], "dashboard_current_invoice")
        self.assertAlmostEqual(capacity["future_card_obligation_total"], 11488.32, places=2)


if __name__ == "__main__":
    unittest.main()
