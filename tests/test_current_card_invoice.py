import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Account, CreditCardBill, ExpectedIncome, Item, Transaction
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.current_card_invoice import current_card_invoice_summary
from app.services.history import credit_card_invoice_purchases_monthly_summary
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

    def _add_item(self, session, item_id="item-1", active=True, connector_name="Itaú"):
        session.add(
            Item(
                id=item_id,
                connector_id="connector-1",
                connector_name=connector_name,
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
        name="Cartão",
        number=None,
        brand=None,
        due_date=date(2026, 6, 8),
    ):
        session.add(
            Account(
                id=account_id,
                item_id=item_id,
                name=name,
                type="CREDIT",
                number=number,
                credit_brand=brand,
                balance=balance,
                credit_balance_due_date=due_date,
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

    def test_current_invoice_excludes_stale_pending_from_previous_months(self):
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
        self.assertEqual(summary["amount"], 300.0)
        self.assertEqual(sum(category["total"] for category in summary["categories"]), 300.0)
        self.assertEqual(summary["transaction_count"], 1)
        self.assertEqual(
            {tx["id"] for tx in summary["raw_purchase_transactions"]},
            {"jul"},
        )

    def test_itau_all_signed_pending_through_cutoff_match_on_all_surfaces(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(session, name="LATAM PASS ITAU MASTERCARD BLACK")
            self._add_purchase(session, "october-installments", date(2026, 10, 6), 3624.86)
            for tx_id, tx_date, amount, forecast in (
                ("old-fee", date(2026, 7, 30), "105", "2026-08"),
                ("new-points", date(2026, 8, 29), "85.75", "2026-10"),
                ("monthly-fee", date(2026, 8, 30), "113", "2026-10"),
                ("old-pending", date(2026, 9, 8), "5079.65", "2026-09"),
                # Forecast cannot pull November into October's pending balance.
                ("next-points", date(2026, 11, 1), "85.75", "2026-10"),
            ):
                session.add(Transaction(
                    id=tx_id,
                    account_id="credit-1",
                    date=tx_date,
                    amount=Decimal(amount),
                    description=tx_id,
                    category="Shopping",
                    status="PENDING",
                    bill_forecast_month=forecast,
                ))
            for tx_id, tx_date in (
                ("transfer-installment-september", date(2026, 9, 6)),
                ("transfer-installment-october", date(2026, 10, 31)),
            ):
                self._add_purchase(
                    session, tx_id, tx_date, 216.68, category="Transfers", ignored=True,
                    description="PAGAMENTO*Mundo a 04/06",
                )
            self._add_purchase(
                session, "pending-payment", date(2026, 8, 20), -5401.33,
                description="PAGAMENTO COM SALDO", category="Transfers", ignored=True,
            )
            self._add_purchase(session, "posted", date(2026, 10, 6), 800, status="POSTED")
            self._add_purchase(session, "unknown", date(2026, 10, 6), 700, status=None)
            self._add_purchase(session, "duplicate", date(2026, 10, 6), 600, duplicate=True)
            session.commit()
            before = [tx.model_dump() for tx in session.exec(select(Transaction)).all()]

        with Session(self.engine) as session:
            today = date(2026, 9, 3)
            current = current_card_invoice_summary(session, today=today)
            upcoming = upcoming_summary(session, today=today)
            planning = planning_month_summary(session, "2026-10", today=today)
            self.assertEqual(before, [tx.model_dump() for tx in session.exec(select(Transaction)).all()])

        october = next(row for row in upcoming["months"] if row["month"] == "2026-10")
        self.assertAlmostEqual(current["amount"], 4040.29)
        self.assertAlmostEqual(october["total"], 4040.29)
        self.assertAlmostEqual(planning["credit_card_invoice"]["amount"], 4040.29)
        self.assertAlmostEqual(planning["capacity"]["card_invoice_gross_total"], 4040.29)
        self.assertAlmostEqual(sum(row["total"] for row in current["categories"]), 4040.29)
        self.assertAlmostEqual(sum(row["total"] for row in october["categories"]), 4040.29)
        self.assertEqual(
            next(row for row in current["categories"] if row["name"] == "Pagamentos da fatura")["total"],
            -5401.33,
        )
        expected_ids = {
            "october-installments", "new-points", "monthly-fee", "old-fee", "old-pending",
            "transfer-installment-september", "transfer-installment-october", "pending-payment",
        }
        self.assertEqual(
            {tx["id"] for tx in current["raw_purchase_transactions"]},
            expected_ids,
        )
        self.assertEqual(
            {tx["id"] for tx in october["transactions"]},
            expected_ids,
        )

    def test_itau_history_excludes_pending_and_groups_posted_by_official_bill(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(session, name="Cartão Itaú Black")
            session.add(CreditCardBill(
                id="august-bill", account_id="credit-1", due_date=date(2026, 8, 6),
                total_amount=Decimal("300"),
            ))
            session.add(Transaction(
                id="closed-purchase", account_id="credit-1", date=date(2026, 7, 10),
                amount=Decimal("300"), description="Compra", category="Shopping",
                status="POSTED", bill_id="august-bill",
            ))
            session.add(Transaction(
                id="still-pending", account_id="credit-1", date=date(2026, 8, 10),
                amount=Decimal("100"), description="Compra pendente", category="Shopping",
                status="PENDING", bill_id="august-bill",
            ))
            session.add(Transaction(
                id="pending-payment", account_id="credit-1", date=date(2026, 8, 20),
                amount=Decimal("-150"), description="PAGAMENTO COM SALDO", category="Transfers",
                status="PENDING", bill_forecast_month="2026-09",
            ))
            session.commit()
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 9, 3)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=2)

        self.assertEqual(history["latest_closed_invoice_month"], "2026-08")
        months = {row["month"]: row for row in history["months"]}
        self.assertNotIn("2026-09", months)
        self.assertNotIn("2026-10", months)
        self.assertEqual(months["2026-08"]["invoice_display_total"], 300)
        self.assertEqual(months["2026-08"]["classified_purchase_total"], 300)
        self.assertEqual(months["2026-07"]["classified_purchase_total"], 0)

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
        self.assertEqual(summary["raw_purchase_transactions"], [])
        self.assertNotIn("reconciliation", summary)
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

        self.assertEqual(sum(row["total"] for row in summary["categories"]), 375.0)
        self.assertEqual(
            {row["id"] for row in summary["raw_purchase_transactions"]},
            {"jul-health"},
        )
        self.assertEqual(summary["recent_purchase_transactions"], [])
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

        self.assertEqual(summary["amount"], 0.0)
        self.assertEqual(summary["transaction_count"], 0)

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
        self.assertEqual(invoice["amount"], 300.0)
        self.assertEqual(invoice["transaction_count"], 1)

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
        self.assertNotIn("next_invoice", summary)
        self.assertNotIn("total_count", summary)
        self.assertTrue(july["is_current_invoice"])
        self.assertEqual(july["total"], 300.0)
        self.assertEqual(sum(tx["amount"] for tx in july["transactions"]), 300.0)
        self.assertEqual(july["count"], 1)
        self.assertEqual(
            {tx["id"] for tx in july["transactions"]},
            {"jul"},
        )
        self.assertEqual(august["total"], 500.0)
        self.assertEqual({tx["id"] for tx in august["transactions"]}, {"aug"})

    def test_future_dated_current_month_purchase_only_appears_in_vigente_invoice(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            self._add_purchase(session, "itau-aug", date(2026, 8, 6), 600)
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 4))
            upcoming = upcoming_summary(session, today=date(2026, 8, 4))

        appearances = [
            month["month"]
            for month in upcoming["months"]
            if "itau-aug" in {tx["id"] for tx in month["transactions"]}
        ]
        self.assertEqual(current["amount"], 0.0)
        current_month = next(month for month in upcoming["months"] if month["is_current_invoice"])
        self.assertEqual(current_month["total"], 0.0)
        self.assertEqual(appearances, [])

    def test_upcoming_identifies_each_card_and_institution(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="Itaú")
            self._add_item(session, item_id="item-caixa", connector_name="CAIXA")
            self._add_credit_account(
                session,
                name="Click Platinum",
                number="1234",
                brand="VISA",
            )
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                item_id="item-caixa",
                name="Cartão CAIXA",
                number="9876",
                brand="MASTERCARD",
            )
            self._add_purchase(session, "itau-buy", date(2026, 7, 10), 100)
            self._add_purchase(
                session,
                "caixa-buy",
                date(2026, 7, 11),
                200,
                account_id="credit-caixa",
            )
            session.commit()

        with Session(self.engine) as session:
            summary = upcoming_summary(session, today=date(2026, 6, 20))

        july, august = summary["months"][:2]
        transactions = {tx["id"]: tx for tx in july["transactions"]}
        self.assertEqual(transactions["itau-buy"]["institution_name"], "Itaú")
        self.assertEqual(transactions["itau-buy"]["card_last_four"], "1234")
        self.assertNotIn("caixa-buy", transactions)
        caixa_transaction = next(tx for tx in august["transactions"] if tx["id"] == "caixa-buy")
        self.assertEqual(caixa_transaction["institution_name"], "CAIXA")
        self.assertEqual(caixa_transaction["card_brand"], "MASTERCARD")
        cards = {card["account_id"]: card for card in july["cards"]}
        self.assertEqual(cards["credit-1"]["total_amount"], 100.0)
        self.assertNotIn("credit-caixa", cards)
        august_cards = {card["account_id"]: card for card in august["cards"]}
        self.assertEqual(august_cards["credit-caixa"]["total_amount"], 200.0)
        self.assertNotIn("closing_day", august_cards["credit-caixa"])

    def test_caixa_statement_markers_are_exact_normalized_and_caixa_scoped(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_item(session, item_id="item-caixa", connector_name="MeuPluggy")
            self._add_credit_account(session, name="LATAM PASS ITAU MASTERCARD BLACK")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                item_id="item-caixa",
                name="CAIXA ICONE VISA",
                due_date=date(2026, 9, 3),
            )
            self._add_purchase(
                session,
                "caixa-marker-spaces",
                date(2026, 7, 24),
                1080.69,
                account_id="credit-caixa",
                description="  Total   da Fátura Anterior  ",
            )
            self._add_purchase(
                session,
                "caixa-marker-punctuation",
                date(2026, 7, 24),
                1080.69,
                account_id="credit-caixa",
                description="TOTAL.DA/FATURA-ANTERIOR",
            )
            self._add_purchase(
                session,
                "caixa-similar-legitimate",
                date(2026, 7, 24),
                90,
                account_id="credit-caixa",
                description="Compra total da fatura anterior na livraria",
            )
            self._add_purchase(
                session,
                "caixa-normal",
                date(2026, 7, 24),
                200,
                account_id="credit-caixa",
                description="Compra normal CAIXA",
            )
            self._add_purchase(
                session,
                "itau-same-description",
                date(2026, 8, 1),
                80,
                description="TOTAL DA FATURA ANTERIOR",
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 4))
            upcoming = upcoming_summary(session, today=date(2026, 8, 4))

        expected_ids = {
            "caixa-similar-legitimate",
            "caixa-normal",
            "itau-same-description",
        }
        self.assertEqual(current["amount"], 370.0)
        self.assertEqual(
            {tx["id"] for tx in current["raw_purchase_transactions"]},
            expected_ids,
        )
        september = next(month for month in upcoming["months"] if month["month"] == "2026-09")
        self.assertEqual(september["total"], 370.0)
        self.assertEqual({tx["id"] for tx in september["transactions"]}, expected_ids)
        self.assertEqual(sum(category["total"] for category in current["categories"]), 370.0)
        self.assertEqual(
            next(card for card in current["cards"] if card["account_id"] == "credit-caixa")["total_amount"],
            290.0,
        )

    def test_caixa_automatic_boleto_payment_does_not_reduce_upcoming_invoice(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                brand="VISA",
                due_date=date(2026, 10, 3),
            )
            session.add_all(
                [
                    Transaction(
                        id="caixa-october-purchase",
                        account_id="credit-caixa",
                        date=date(2026, 8, 25),
                        amount=Decimal("10000"),
                        description="Compra CAIXA",
                        category="Shopping",
                        pluggy_raw_category="Shopping",
                        pluggy_raw_type="DEBIT",
                        status="PENDING",
                        bill_forecast_month="2026-09",
                        credit_card_last_four="6849",
                    ),
                    Transaction(
                        id="caixa-automatic-boleto-payment",
                        account_id="credit-caixa",
                        date=date(2026, 8, 31),
                        amount=Decimal("-8418.39"),
                        description="AUT. PGTO. BOLETO REGISTRADO",
                        category="Transfer - Bank Slip",
                        pluggy_raw_category="Transfer - Bank Slip",
                        pluggy_raw_type="CREDIT",
                        status="PENDING",
                        bill_forecast_month="2026-09",
                        credit_card_last_four="6849",
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 9, 1))
            upcoming = upcoming_summary(session, today=date(2026, 9, 1))

        self.assertEqual(current["amount"], 10000.0)
        self.assertEqual(
            {tx["id"] for tx in current["raw_purchase_transactions"]},
            {"caixa-october-purchase"},
        )
        october = next(month for month in upcoming["months"] if month["month"] == "2026-10")
        self.assertTrue(october["is_current_invoice"])
        self.assertEqual(october["total"], 10000.0)
        self.assertEqual(
            {tx["id"] for tx in october["transactions"]},
            {"caixa-october-purchase"},
        )
        self.assertNotIn(
            "Créditos / Estornos",
            {category["name"] for category in october["categories"]},
        )

    def test_history_uses_card_payments_as_closed_invoice_and_excludes_open_month(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_item(session, item_id="item-caixa", connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                name="LATAM PASS ITAU MASTERCARD BLACK",
                number="3279",
                due_date=date(2026, 8, 6),
            )
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                item_id="item-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                due_date=date(2026, 8, 3),
            )
            session.add_all(
                [
                    Transaction(
                        id="itau-september-payment",
                        account_id="credit-1",
                        date=date(2026, 8, 20),
                        amount=Decimal("-5401.33"),
                        description="PAGAMENTO COM SALDO",
                        category="Transfers",
                        status="POSTED",
                        bill_forecast_month="2026-09",
                    ),
                    Transaction(
                        id="caixa-september-payment",
                        account_id="credit-caixa",
                        date=date(2026, 8, 31),
                        amount=Decimal("-8418.39"),
                        description="AUT. PGTO. BOLETO REGISTRADO",
                        category="Transfer - Bank Slip",
                        status="PENDING",
                        bill_forecast_month="2026-09",
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 9, 1)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=2)

        months = {month["month"]: month for month in history["months"]}
        self.assertEqual(history["latest_closed_invoice_month"], "2026-09")
        self.assertNotIn("2026-10", months)
        self.assertEqual(months["2026-09"]["invoice_display_total"], 13819.72)
        self.assertFalse(months["2026-09"]["is_current_invoice"])
        cards = {card["account_name"]: card["total"] for card in months["2026-09"]["cards"]}
        self.assertEqual(cards["CAIXA ICONE VISA"], 8418.39)
        self.assertEqual(cards["LATAM PASS ITAU MASTERCARD BLACK"], 5401.33)

    def test_caixa_previous_bill_marker_does_not_change_closed_history_or_payment(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                due_date=date(2026, 8, 3),
            )
            session.add(
                CreditCardBill(
                    id="caixa-august-official",
                    account_id="credit-caixa",
                    due_date=date(2026, 8, 3),
                    total_amount=Decimal("1080.69"),
                )
            )
            session.add_all(
                [
                    Transaction(
                        id="caixa-closed-purchase",
                        account_id="credit-caixa",
                        date=date(2026, 7, 20),
                        amount=Decimal("1080.69"),
                        description="Compras da fatura fechada",
                        category="Shopping",
                        status="POSTED",
                        bill_id="caixa-august-official",
                    ),
                    Transaction(
                        id="caixa-closed-payment",
                        account_id="credit-caixa",
                        date=date(2026, 8, 3),
                        amount=Decimal("-1080.69"),
                        description="Pagamento recebido",
                        category="Credit card payment",
                        status="POSTED",
                        bill_id="caixa-august-official",
                    ),
                    Transaction(
                        id="caixa-previous-total-current",
                        account_id="credit-caixa",
                        date=date(2026, 7, 24),
                        amount=Decimal("1080.69"),
                        description="TOTAL DA FATURA ANTERIOR",
                        category="Other",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                    ),
                    Transaction(
                        id="caixa-current-purchase",
                        account_id="credit-caixa",
                        date=date(2026, 7, 24),
                        amount=Decimal("300"),
                        description="Compra da fatura vigente",
                        category="Shopping",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 10))
            upcoming = upcoming_summary(session, today=date(2026, 8, 10))
            marker_is_preserved = (
                session.get(Transaction, "caixa-previous-total-current") is not None
            )
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 8, 10)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=2)

        months = {month["month"]: month for month in history["months"]}
        self.assertEqual(current["amount"], 300.0)
        current_month = next(month for month in upcoming["months"] if month["is_current_invoice"])
        self.assertEqual(current_month["total"], 300.0)
        self.assertTrue(marker_is_preserved)
        self.assertEqual(
            {tx["id"] for tx in current["raw_purchase_transactions"]}, {"caixa-current-purchase"}
        )
        self.assertNotIn("invoice_total_source", months["2026-08"])
        self.assertEqual(months["2026-08"]["invoice_display_total"], 1080.69)
        self.assertNotIn("2026-09", months)

    def test_caixa_marker_is_excluded_from_available_to_spend(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                due_date=date(2026, 9, 3),
            )
            session.add(
                ExpectedIncome(description="Salário", amount=Decimal("5000"), expected_day=5)
            )
            self._add_purchase(
                session,
                "caixa-current",
                date(2026, 7, 24),
                300,
                account_id="credit-caixa",
                description="Compra vigente",
            )
            self._add_purchase(
                session,
                "caixa-previous-total",
                date(2026, 7, 24),
                1080.69,
                account_id="credit-caixa",
                description="TOTAL DA FATURA ANTERIOR",
            )
            session.commit()

        with Session(self.engine) as session:
            planning = planning_month_summary(
                session,
                "2026-09",
                today=date(2026, 8, 10),
            )

        self.assertEqual(planning["credit_card_invoice"]["amount"], 300.0)
        self.assertEqual(planning["capacity"]["future_card_obligation_total"], 300.0)
        self.assertEqual(planning["capacity"]["budget_available_to_spend"], 4700.0)

    def test_caixa_current_invoice_reconciles_dashboard_history_and_upcoming(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                name="LATAM PASS ITAU MASTERCARD BLACK",
                number="3279",
                due_date=date(2026, 7, 6),
            )
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                brand="VISA",
                balance=Decimal("14870.17"),
                due_date=date(2026, 8, 3),
            )
            self._add_purchase(session, "itau-aug", date(2026, 8, 6), 600)
            self._add_purchase(
                session,
                "caixa-before-close",
                date(2026, 7, 23),
                400,
                account_id="credit-caixa",
            )
            self._add_purchase(
                session,
                "caixa-after-close",
                date(2026, 7, 24),
                300,
                account_id="credit-caixa",
            )
            session.add(
                CreditCardBill(
                    id="caixa-aug-bill",
                    account_id="credit-caixa",
                    due_date=date(2026, 8, 3),
                    total_amount=Decimal("1080.69"),
                    minimum_payment_amount=Decimal("162.11"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 4))
            summary = upcoming_summary(session, today=date(2026, 8, 4))
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 8, 4)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=1)

        months = {month["month"]: month for month in summary["months"]}
        september = months["2026-09"]
        transaction_ids = {tx["id"] for tx in september["transactions"]}

        self.assertNotIn("2026-08", months)
        self.assertEqual(current["amount"], 900.0)
        self.assertEqual(september["total"], 900.0)
        self.assertEqual(history["months"][0]["invoice_display_total"], 1080.69)
        self.assertEqual(transaction_ids, {"caixa-after-close", "itau-aug"})
        self.assertNotIn("caixa-before-close", transaction_ids)
        september_cards = {card["account_id"]: card for card in september["cards"]}
        self.assertEqual(september_cards["credit-1"]["total_amount"], 600.0)
        self.assertEqual(september_cards["credit-caixa"]["total_amount"], 300.0)
        self.assertNotIn("is_official", september_cards["credit-caixa"])

    def test_caixa_official_vigente_bill_has_same_priority_everywhere(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="CAIXA")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                due_date=date(2026, 9, 3),
            )
            session.add(
                Transaction(
                    id="caixa-september-purchase",
                    account_id="credit-caixa",
                    date=date(2026, 7, 24),
                    amount=Decimal("200"),
                    description="Compra CAIXA",
                    category="Shopping",
                    status="PENDING",
                    bill_forecast_month="2026-08",
                )
            )
            session.add(
                CreditCardBill(
                    id="caixa-september-bill",
                    account_id="credit-caixa",
                    due_date=date(2026, 9, 3),
                    total_amount=Decimal("777"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 4))
            upcoming = upcoming_summary(session, today=date(2026, 8, 4))
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 8, 4)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=1)

        self.assertEqual(current["amount"], 777.0)
        current_month = next(month for month in upcoming["months"] if month["is_current_invoice"])
        self.assertEqual(current_month["total"], 777.0)
        self.assertEqual(history["months"][0]["invoice_display_total"], 777.0)
        detailed_total = sum(tx["signed_amount"] for tx in current["raw_purchase_transactions"])
        self.assertEqual(detailed_total, 200.0)
        self.assertEqual(current["amount"] - detailed_total, 577.0)
        self.assertEqual(current["cards"][0]["total_amount"], 777.0)
        self.assertNotIn("invoice_source", current["cards"][0])
        self.assertNotIn("is_official", current["cards"][0])

    def test_caixa_uses_forecast_credits_and_projects_known_installments(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                brand="VISA",
                balance=Decimal("20476.90"),
                due_date=date(2026, 8, 3),
            )
            session.add_all(
                [
                    Transaction(
                        id="caixa-current-purchase",
                        account_id="credit-caixa",
                        date=date(2026, 7, 24),
                        amount=Decimal("200"),
                        description="NOVA SANTA RITA",
                        category="Gas stations",
                        pluggy_raw_category="Gas stations",
                        pluggy_raw_type="DEBIT",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                        credit_card_last_four="9755",
                    ),
                    Transaction(
                        id="caixa-current-credit",
                        account_id="credit-caixa",
                        date=date(2026, 8, 1),
                        amount=Decimal("-23.35"),
                        description="IOF Zero CAIXA Visa",
                        category="Shopping",
                        pluggy_raw_category="Shopping",
                        pluggy_raw_type="CREDIT",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                        credit_card_last_four="6849",
                    ),
                    Transaction(
                        id="caixa-installment-base",
                        account_id="credit-caixa",
                        date=date(2026, 7, 24),
                        purchase_date=date(2026, 7, 16),
                        amount=Decimal("348"),
                        description="PANVEL*DIGITAL",
                        category="Pharmacy",
                        pluggy_raw_category="Pharmacy",
                        pluggy_raw_type="DEBIT",
                        status="PENDING",
                        bill_forecast_month="2026-07",
                        credit_card_last_four="6849",
                        installment_number=1,
                        total_installments=5,
                    ),
                    Transaction(
                        id="caixa-previous-total",
                        account_id="credit-caixa",
                        date=date(2026, 7, 24),
                        amount=Decimal("1080.69"),
                        description="TOTAL DA FATURA ANTERIOR",
                        category="Other",
                        pluggy_raw_category="Other",
                        pluggy_raw_type="DEBIT",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                    ),
                    Transaction(
                        id="caixa-previous-payment",
                        account_id="credit-caixa",
                        date=date(2026, 7, 29),
                        amount=Decimal("-1080.69"),
                        description="PGTO.BOLETO REGISTRADO",
                        category="Transfer - Bank Slip",
                        pluggy_raw_category="Transfer - Bank Slip",
                        pluggy_raw_type="CREDIT",
                        status="PENDING",
                        bill_forecast_month="2026-08",
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            current = current_card_invoice_summary(session, today=date(2026, 8, 4))
            summary = upcoming_summary(session, today=date(2026, 8, 4))
            with patch("app.services.history.date") as history_date:
                history_date.today.return_value = date(2026, 8, 4)
                history_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                history = credit_card_invoice_purchases_monthly_summary(session, months=1)

        september = next(month for month in summary["months"] if month["month"] == "2026-09")
        self.assertAlmostEqual(current["amount"], 524.65)
        self.assertTrue(september["is_current_invoice"])
        self.assertAlmostEqual(history["months"][0]["invoice_display_total"], 1080.69)
        self.assertNotIn("invoice_total_source", history["months"][0])
        self.assertAlmostEqual(september["total"], 524.65)
        self.assertAlmostEqual(
            sum(tx["signed_amount"] for tx in september["transactions"]), 524.65
        )
        self.assertEqual(september["count"], 3)
        transactions = {tx["id"]: tx for tx in september["transactions"]}
        self.assertEqual(
            set(transactions),
            {
                "caixa-current-purchase",
                "caixa-current-credit",
                "caixa-installment-base:projected:2",
            },
        )
        projected = transactions["caixa-installment-base:projected:2"]
        self.assertTrue(projected["is_projected"])
        self.assertEqual(projected["installment_number"], 2)
        self.assertEqual(projected["total_installments"], 5)
        self.assertEqual(projected["date"], "2026-07-16")
        self.assertEqual(transactions["caixa-current-purchase"]["card_last_four"], "9755")
        self.assertEqual(transactions["caixa-current-credit"]["signed_amount"], -23.35)
        self.assertEqual(
            {tx["id"] for tx in current["raw_purchase_transactions"]},
            set(transactions),
        )
        history_categories = {
            category["name"]: category for category in history["months"][0]["categories"]
        }
        self.assertNotIn("Créditos / Estornos", history_categories)

        card = next(card for card in september["cards"] if card["account_id"] == "credit-caixa")
        self.assertAlmostEqual(card["total_amount"], 524.65)
        self.assertEqual(projected["amount"], 348.0)
        self.assertEqual(sum(bool(tx.get("is_projected")) for tx in transactions.values()), 1)

    def test_caixa_projects_future_invoices_from_posted_installment_anchor(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="CAIXA")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                brand="VISA",
                due_date=date(2026, 8, 3),
            )
            session.add(
                Transaction(
                    id="caixa-posted-installment-1",
                    account_id="credit-caixa",
                    date=date(2026, 7, 24),
                    purchase_date=date(2026, 7, 24),
                    amount=Decimal("125"),
                    description="COMPRA PARCELADA",
                    category="Shopping",
                    pluggy_raw_category="Shopping",
                    pluggy_raw_type="DEBIT",
                    status="POSTED",
                    bill_forecast_month="2026-07",
                    credit_card_last_four="6849",
                    installment_number=1,
                    total_installments=3,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            summary = upcoming_summary(session, today=date(2026, 8, 4))

        months = {month["month"]: month for month in summary["months"]}
        for month, installment_number in (("2026-09", 2), ("2026-10", 3)):
            row = months[month]
            caixa_card = next(card for card in row["cards"] if card["account_id"] == "credit-caixa")
            self.assertEqual(caixa_card["total_amount"], 125.0)
            self.assertEqual(len(row["transactions"]), 1)
            self.assertEqual(row["total"], 125.0)
            transaction = next(
                tx for tx in row["transactions"] if tx["account_id"] == "credit-caixa"
            )
            self.assertTrue(transaction["is_projected"])
            self.assertEqual(transaction["installment_number"], installment_number)
            self.assertEqual(transaction["total_installments"], 3)

    def test_caixa_does_not_duplicate_an_installment_already_returned_by_pluggy(self):
        with Session(self.engine) as session:
            self._add_item(session, connector_name="MeuPluggy")
            self._add_credit_account(
                session,
                account_id="credit-caixa",
                name="CAIXA ICONE VISA",
                number="6849",
                due_date=date(2026, 8, 3),
            )
            common = {
                "account_id": "credit-caixa",
                "purchase_date": date(2026, 7, 16),
                "amount": Decimal("348"),
                "description": "PANVEL*DIGITAL",
                "category": "Pharmacy",
                "pluggy_raw_category": "Pharmacy",
                "pluggy_raw_type": "DEBIT",
                "status": "PENDING",
                "credit_card_last_four": "6849",
                "total_installments": 5,
            }
            session.add_all(
                [
                    Transaction(
                        id="caixa-installment-1",
                        date=date(2026, 7, 24),
                        bill_forecast_month="2026-07",
                        installment_number=1,
                        **common,
                    ),
                    Transaction(
                        id="caixa-installment-2",
                        date=date(2026, 8, 24),
                        bill_forecast_month="2026-08",
                        installment_number=2,
                        **common,
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            summary = upcoming_summary(session, today=date(2026, 8, 4))

        september = next(month for month in summary["months"] if month["month"] == "2026-09")
        caixa_rows = [tx for tx in september["transactions"] if tx["account_id"] == "credit-caixa"]
        self.assertEqual(len(caixa_rows), 1)
        self.assertEqual(caixa_rows[0]["id"], "caixa-installment-2")
        self.assertFalse(caixa_rows[0]["is_projected"])

    def test_planning_capacity_and_variable_budget_use_pending_ids(self):
        with Session(self.engine) as session:
            self._add_item(session)
            self._add_credit_account(session)
            session.add(
                ExpectedIncome(description="Salário", amount=Decimal("5000"), expected_day=5)
            )
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

        capacity = planning["capacity"]
        self.assertEqual(planning["credit_card_invoice"]["amount"], 300.0)
        self.assertEqual(capacity["card_invoice_source"], "pending_current_invoice")
        self.assertEqual(capacity["future_card_obligation_total"], 300.0)
        self.assertEqual(capacity["variable_budget_consumed"], 300.0)
        self.assertEqual(planning["variable_budgets"]["remaining"], 700.0)

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
        self.assertEqual(summary["amount"], 200.0)
        self.assertEqual(
            {tx["id"] for tx in summary["raw_purchase_transactions"]},
            {"jan"},
        )


if __name__ == "__main__":
    unittest.main()
