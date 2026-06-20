import unittest
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, CreditCardBill, ExpectedIncome, Item, Transaction
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.current_card_invoice import current_card_invoice_summary
from app.services.planning import planning_month_summary
from app.services.transaction_reports import upcoming_summary
from app.services.variable_budgets import upsert_goal


class CurrentCardInvoicePendingTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        SQLModel.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _add_item(self, session, item_id="item-1", active=True):
        session.add(
            Item(
                id=item_id,
                connector_id="connector-1",
                status="UPDATED",
                is_active=active,
            )
        )

    def _add_credit_account(
        self,
        session,
        account_id="credit-1",
        item_id="item-1",
        balance=Decimal("0"),
        active=True,
    ):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name="Cartão",
                type="CREDIT",
                balance=balance,
                credit_balance_due_date=date(2026, 6, 8),
                balance_updated_at=datetime(2026, 6, 20, 12, 0),
                is_active=active,
            )
        )

    def _add_purchase(
        self,
        session,
        tx_id,
        tx_date,
        amount,
        *,
        status="PENDING",
        category="Shopping",
        account_id="credit-1",
        duplicate=False,
        ignored=False,
        description="Compra",
    ):
        session.add(
            Transaction(
                id=tx_id,
                account_id=account_id,
                date=tx_date,
                amount=Decimal(str(amount)),
                description=description,
                category=category,
                status=status,
                is_duplicate=duplicate,
                ignored_from_totals=ignored,
            )
        )

    def test_current_invoice_is_only_pending_through_invoice_month(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("99999"))
            self._add_purchase(session, "may", date(2026, 5, 30), 100)
            self._add_purchase(session, "jun", date(2026, 6, 10), 200)
            self._add_purchase(session, "jul", date(2026, 7, 10), 300)
            self._add_purchase(session, "aug", date(2026, 8, 10), 400)
            self._add_purchase(session, "posted", date(2026, 6, 10), 500, status="POSTED")
            self._add_purchase(session, "duplicate", date(2026, 6, 10), 600, duplicate=True)
            self._add_purchase(session, "ignored", date(2026, 6, 10), 700, ignored=True)
            self._add_purchase(
                session,
                "refund",
                date(2026, 6, 10),
                -80,
                description="Estorno compra",
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 20))

        self.assertEqual(summary["invoice_month"], "2026-07")
        self.assertEqual(summary["cutoff_date"], "2026-07-31")
        self.assertEqual(summary["source"], "pending_transactions")
        self.assertEqual(summary["amount"], 600.0)
        self.assertEqual(summary["category_total"], 600.0)
        self.assertEqual(summary["category_count"], 3)
        self.assertEqual(
            {tx["id"] for tx in summary["raw_purchase_transactions"]},
            {"may", "jun", "jul"},
        )

    def test_balance_and_bills_never_enter_current_invoice(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("28619.60"))
            session.add(
                CreditCardBill(
                    id="closed-bill",
                    account_id="credit-1",
                    due_date=date(2026, 6, 8),
                    total_amount=Decimal("17131.28"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 20))

        self.assertEqual(summary["amount"], 0.0)
        self.assertEqual(summary["categories"], [])
        self.assertEqual(summary["reconciliation"]["unreconciled_amount"], 0.0)
        self.assertNotIn("raw_account_balance_total", summary)
        self.assertNotIn("adjusted_total", summary)

    def test_categories_and_recent_purchases_use_the_same_pending_set(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            self._add_purchase(
                session,
                "jun-food",
                date(2026, 6, 10),
                125,
                category="Groceries",
            )
            self._add_purchase(
                session,
                "jul-health",
                date(2026, 7, 10),
                375,
                category="Healthcare",
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 20))

        self.assertEqual(sum(row["total"] for row in summary["categories"]), 500.0)
        self.assertEqual(
            {row["id"] for row in summary["raw_purchase_transactions"]},
            {"jun-food", "jul-health"},
        )
        self.assertEqual(
            {row["id"] for row in summary["recent_purchase_transactions"]},
            {"jun-food"},
        )
        self.assertNotIn(
            "account_balance_reconciliation",
            {row.get("source") for row in summary["categories"]},
        )

    def test_inactive_accounts_and_items_are_excluded(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_item(session, item_id="inactive-item", active=False)
            self._add_credit_account(session)
            self._add_credit_account(
                session,
                account_id="inactive-account",
                active=False,
            )
            self._add_credit_account(
                session,
                account_id="inactive-item-account",
                item_id="inactive-item",
            )
            self._add_purchase(session, "active", date(2026, 6, 10), 100)
            self._add_purchase(
                session,
                "inactive",
                date(2026, 6, 10),
                900,
                account_id="inactive-account",
            )
            self._add_purchase(
                session,
                "inactive-item-tx",
                date(2026, 6, 10),
                500,
                account_id="inactive-item-account",
            )
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 6, 20))

        self.assertEqual(summary["amount"], 100.0)
        self.assertEqual(summary["category_count"], 1)

    def test_planning_vigente_uses_pending_even_when_official_bill_exists(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("9000"))
            self._add_purchase(session, "jun", date(2026, 6, 10), 100)
            self._add_purchase(session, "jul", date(2026, 7, 10), 300)
            session.add(
                CreditCardBill(
                    id="jul-bill",
                    account_id="credit-1",
                    due_date=date(2026, 7, 8),
                    total_amount=Decimal("7000"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            invoice = planning_invoice_for_month(
                session,
                "2026-07",
                today=date(2026, 6, 20),
            )

        self.assertEqual(invoice["source"], "pending_current_invoice")
        self.assertEqual(invoice["amount"], 400.0)
        self.assertEqual(invoice["transaction_count"], 2)

    def test_future_month_keeps_official_invoice_logic(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            self._add_purchase(session, "aug", date(2026, 8, 10), 500)
            session.add(
                CreditCardBill(
                    id="aug-bill",
                    account_id="credit-1",
                    due_date=date(2026, 8, 8),
                    total_amount=Decimal("600"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            invoice = planning_invoice_for_month(
                session,
                "2026-08",
                today=date(2026, 6, 20),
            )

        self.assertEqual(invoice["source"], "official_bill")
        self.assertEqual(invoice["amount"], 600.0)

    def test_upcoming_reuses_pending_current_invoice_and_keeps_future_months(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session, balance=Decimal("10000"))
            self._add_purchase(session, "may", date(2026, 5, 30), 100)
            self._add_purchase(session, "jun", date(2026, 6, 10), 200)
            self._add_purchase(session, "jul", date(2026, 7, 10), 300)
            self._add_purchase(session, "aug", date(2026, 8, 10), 500)
            session.commit()

        with Session(self.engine) as session:
            summary = upcoming_summary(session, today=date(2026, 6, 20))

        july, august = summary["months"][:2]
        self.assertEqual(summary["next_invoice"]["amount"], 600.0)
        self.assertEqual(summary["next_invoice"]["source"], "pending_current_invoice")
        self.assertEqual(july["total"], 600.0)
        self.assertEqual(july["detailed_total"], 600.0)
        self.assertEqual(july["count"], 3)
        self.assertEqual(
            {tx["id"] for tx in july["transactions"]},
            {"may", "jun", "jul"},
        )
        self.assertEqual(august["total"], 500.0)
        self.assertEqual({tx["id"] for tx in august["transactions"]}, {"aug"})

    def test_planning_capacity_and_variable_budget_use_pending_ids(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            session.add(ExpectedIncome(description="Salário", amount=Decimal("5000"), expected_day=5))
            upsert_goal(session, "2026-07", "Alimentação", 1000)
            self._add_purchase(
                session,
                "jun-food",
                date(2026, 6, 10),
                200,
                category="Groceries",
            )
            self._add_purchase(
                session,
                "jul-food",
                date(2026, 7, 10),
                300,
                category="Groceries",
            )
            session.commit()

        with Session(self.engine) as session:
            planning = planning_month_summary(
                session,
                "2026-07",
                today=date(2026, 6, 20),
            )

        capacity = planning["raw"]["spending_capacity"]
        self.assertEqual(planning["credit_card_invoice"]["amount"], 500.0)
        self.assertEqual(capacity["card_invoice_source"], "pending_current_invoice")
        self.assertEqual(capacity["future_card_obligation_total"], 500.0)
        self.assertEqual(capacity["variable_budget_consumed"], 500.0)
        self.assertEqual(planning["variable_budgets"]["remaining"], 500.0)

    def test_december_rolls_current_invoice_cutoff_into_january(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            self._add_purchase(session, "dec", date(2026, 12, 20), 100)
            self._add_purchase(session, "jan", date(2027, 1, 15), 200)
            self._add_purchase(session, "feb", date(2027, 2, 5), 300)
            session.commit()

        with Session(self.engine) as session:
            summary = current_card_invoice_summary(session, today=date(2026, 12, 20))

        self.assertEqual(summary["invoice_month"], "2027-01")
        self.assertEqual(summary["amount"], 300.0)
        self.assertEqual(
            {tx["id"] for tx in summary["raw_purchase_transactions"]},
            {"dec", "jan"},
        )


if __name__ == "__main__":
    unittest.main()
