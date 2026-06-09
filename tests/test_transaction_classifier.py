import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, Item, Transaction
from app.services.transaction_classifier import (
    ClassificationInput,
    classify_input,
    classify_pluggy_payload,
)
from scripts.reclassify_transactions_v2 import reclassify


class TransactionClassifierTest(unittest.TestCase):
    def assert_classification(
        self,
        raw_category,
        internal_category,
        cashflow_type,
        confidence="high",
        ignored_from_totals=False,
        amount=Decimal("-10"),
        account_type="CREDIT",
    ):
        result = classify_input(
            ClassificationInput(
                pluggy_raw_category=raw_category,
                amount=amount,
                account_type=account_type,
            )
        )
        self.assertEqual(result.internal_category, internal_category)
        self.assertEqual(result.cashflow_type, cashflow_type)
        self.assertEqual(result.confidence, confidence)
        self.assertEqual(result.ignored_from_totals, ignored_from_totals)
        self.assertEqual(result.source, "pluggy_rule")

    def test_core_pluggy_category_rules(self):
        cases = [
            ("food", "Alimentação", "expense", False),
            ("delivery", "Alimentação", "expense", False),
            ("market", "Alimentação", "expense", False),
            ("transport", "Transporte", "expense", False),
            ("fuel", "Transporte", "expense", False),
            ("income", "Receitas", "income", False),
            ("transfer", "Transferências", "transfer", True),
            ("credit_card_payment", "Pagamento de cartão", "credit_card_payment", True),
            ("refund", "Estorno", "refund", False),
            ("investment", "Investimentos", "investment", True),
        ]
        for raw, category, cashflow_type, ignored in cases:
            with self.subTest(raw=raw):
                self.assert_classification(
                    raw,
                    category,
                    cashflow_type,
                    ignored_from_totals=ignored,
                )

    def test_real_pluggy_values_seen_in_local_diagnosis(self):
        cases = [
            ("Shopping", "Compras", "expense"),
            ("Office supplies", "Compras", "expense"),
            ("Eating out", "Alimentação", "expense"),
            ("Transfer - PIX", "Transferências", "transfer"),
            ("Same person transfer", "Transferências", "transfer"),
            ("Credit card payment", "Pagamento de cartão", "credit_card_payment"),
            ("Fixed income", "Investimentos", "investment"),
            ("Proceeds interests and dividends", "Receitas", "income"),
        ]
        for raw, category, cashflow_type in cases:
            with self.subTest(raw=raw):
                result = classify_input(
                    ClassificationInput(
                        pluggy_raw_category=raw,
                        amount=Decimal("-1"),
                    )
                )
                self.assertEqual(result.internal_category, category)
                self.assertEqual(result.cashflow_type, cashflow_type)

    def test_unknown_category_uses_new_low_confidence_fallback(self):
        result = classify_input(
            ClassificationInput(
                pluggy_raw_category="totally new pluggy category",
                amount=Decimal("-12.34"),
            )
        )
        self.assertEqual(result.internal_category, "Outros")
        self.assertEqual(result.cashflow_type, "expense")
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.matched_rule, "amount_sign:nonzero")

    def test_payload_classification_does_not_use_legacy_category_id(self):
        result = classify_pluggy_payload(
            {
                "id": "tx-1",
                "category": "Food delivery",
                "category_id": 999,
                "amount": -42,
                "description": "Lunch",
            },
            account_type="CREDIT",
        )
        values = result.transaction_values()
        self.assertEqual(values["internal_category"], "Alimentação")
        self.assertNotIn("category_id", values)


class TransactionReclassificationScriptTest(unittest.TestCase):
    def test_dry_run_does_not_mutate_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "classification.db"
            engine = create_engine(f"sqlite:///{db_path}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Item(id="item-1", connector_id=1, status="UPDATED"))
                session.add(
                    Account(
                        id="acc-1",
                        item_id="item-1",
                        name="Card",
                        type="CREDIT",
                        is_active=True,
                    )
                )
                session.add(
                    Transaction(
                        id="tx-1",
                        account_id="acc-1",
                        date=date(2026, 6, 9),
                        amount=Decimal("-42.00"),
                        description="Lunch",
                        category="Food delivery",
                    )
                )
                session.commit()

            result = reclassify(f"sqlite:///{db_path}", apply=False)
            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["would_change"], 1)

            with Session(engine) as session:
                tx = session.get(Transaction, "tx-1")
                self.assertIsNone(tx.internal_category)
                self.assertIsNone(tx.cashflow_type)
                self.assertIsNone(tx.pluggy_raw_category)


if __name__ == "__main__":
    unittest.main()
