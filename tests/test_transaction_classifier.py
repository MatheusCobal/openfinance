import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction, UserClassificationRule
from app.services.classification import TransactionClassifier, TransactionKind
from app.services.transaction_classifier import (
    ClassificationInput,
    CompiledUserRule,
    classify_input,
    classify_pluggy_payload,
)
from app.services.user_classification_rules import load_compiled_user_rules
from scripts.reclassify_transactions_v2 import reclassify
from scripts.reclassify_user_rules import reclassify_user_rules


def user_rule(
    rule_id=1,
    *,
    priority=100,
    account_type_scope="ALL",
    match_pluggy_category=None,
    match_pluggy_subcategory=None,
    match_pluggy_type=None,
    match_merchant=None,
    match_description=None,
    match_amount_sign="any",
    target_internal_category="Pet",
    target_cashflow_type="expense",
    ignored_from_totals=False,
):
    return CompiledUserRule(
        rule_id=rule_id,
        priority=priority,
        account_type_scope=account_type_scope,
        match_pluggy_category=match_pluggy_category,
        match_pluggy_subcategory=match_pluggy_subcategory,
        match_pluggy_type=match_pluggy_type,
        match_merchant=match_merchant,
        match_description=match_description,
        match_amount_sign=match_amount_sign,
        target_internal_category=target_internal_category,
        target_cashflow_type=target_cashflow_type,
        ignored_from_totals=ignored_from_totals,
    )


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

    def test_expanded_rules_from_10db2_real_data_diagnosis(self):
        # Raw Pluggy values found in the local diagnosis that used to fall
        # into the "Outros" fallback before 10D-B.2.
        cases = [
            ("Sports goods", "Compras", "expense"),
            ("Food and drinks", "Alimentação", "expense"),
            ("Income taxes", "Impostos / Taxas", "expense"),
            ("Vehicle ownership taxes and fees", "Impostos / Taxas", "expense"),
            ("Online Courses", "Educação", "expense"),
            ("Tickets", "Lazer", "expense"),
            ("Leisure", "Lazer", "expense"),
            ("Wellness", "Beleza / Cuidados pessoais", "expense"),
            ("Tolls and in vehicle payment", "Transporte", "expense"),
            ("Housing", "Moradia", "expense"),
            ("Rent", "Moradia", "expense"),
            ("Internet", "Assinaturas", "expense"),
            ("Mobile", "Assinaturas", "expense"),
        ]
        for raw, category, cashflow_type in cases:
            with self.subTest(raw=raw):
                result = classify_input(
                    ClassificationInput(
                        pluggy_raw_category=raw,
                        amount=Decimal("-10"),
                        account_type="CREDIT",
                    )
                )
                self.assertEqual(result.internal_category, category)
                self.assertEqual(result.cashflow_type, cashflow_type)
                self.assertEqual(result.source, "pluggy_rule")
                self.assertFalse(result.ignored_from_totals)

    def test_transfer_internal_is_ignored_transfer(self):
        # "Transfer - Internal" is an account-to-account movement; it must
        # be classified as transfer/ignored so it doesn't pollute totals.
        result = classify_input(
            ClassificationInput(
                pluggy_raw_category="Transfer - Internal",
                amount=Decimal("500.00"),
                account_type="BANK",
            )
        )
        self.assertEqual(result.internal_category, "Transferências")
        self.assertEqual(result.cashflow_type, "transfer")
        self.assertTrue(result.ignored_from_totals)
        self.assertEqual(result.source, "pluggy_rule")

    def test_transfer_bank_slip_is_not_internal_transfer(self):
        # "Transfer - Bank Slip" is a boleto payment — real money leaving
        # the account.  It must NOT be treated as an internal transfer so
        # that real outflows remain visible in cashflow.
        result = classify_input(
            ClassificationInput(
                pluggy_raw_category="Transfer - Bank Slip",
                amount=Decimal("-200.00"),
                account_type="BANK",
            )
        )
        self.assertEqual(result.internal_category, "Outros")
        self.assertEqual(result.cashflow_type, "expense")
        self.assertFalse(result.ignored_from_totals)
        self.assertEqual(result.source, "pluggy_rule")
        self.assertEqual(result.confidence, "medium")

    def test_transfer_bank_slip_positive_is_not_income(self):
        # Positive BANK "Transfer - Bank Slip" must not count as Receitas.
        # cashflow_type=expense is in NON_INCOME_CASHFLOW_TYPES, so the
        # bank income exclusion flag will be set by TransactionClassifier.
        result = classify_input(
            ClassificationInput(
                pluggy_raw_category="Transfer - Bank Slip",
                amount=Decimal("500.00"),
                account_type="BANK",
            )
        )
        self.assertEqual(result.cashflow_type, "expense")
        self.assertFalse(result.ignored_from_totals)

    def test_structural_cashflow_types_stay_ignored_from_totals(self):
        cases = [
            ("Credit card payment", "credit_card_payment"),
            ("Transfer - PIX", "transfer"),
            ("Fixed income", "investment"),
        ]
        for raw, cashflow_type in cases:
            with self.subTest(raw=raw):
                result = classify_input(
                    ClassificationInput(pluggy_raw_category=raw, amount=Decimal("-10"))
                )
                self.assertEqual(result.cashflow_type, cashflow_type)
                self.assertTrue(result.ignored_from_totals)

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


class UserClassificationRuleClassifierTest(unittest.TestCase):
    def test_manual_override_beats_user_rule(self):
        result = classify_input(
            ClassificationInput(
                pluggy_merchant="cobasi",
                amount=Decimal("-10"),
                is_user_overridden=True,
                user_rules=(
                    user_rule(
                        match_merchant="cobasi",
                        target_internal_category="Pet",
                    ),
                ),
            )
        )
        self.assertEqual(result.source, "manual_override")
        self.assertEqual(result.matched_rule, "manual_override:reserved")

    def test_user_rule_beats_pluggy_system_and_fallback(self):
        rule = user_rule(
            match_merchant="ifood",
            target_internal_category="Compras",
            target_cashflow_type="expense",
        )
        pluggy = classify_input(
            ClassificationInput(
                pluggy_raw_category="Food delivery",
                pluggy_merchant="IFOOD SA",
                amount=Decimal("-42"),
                account_type="CREDIT",
                user_rules=(rule,),
            )
        )
        self.assertEqual(pluggy.internal_category, "Compras")
        self.assertEqual(pluggy.source, "user_rule")
        self.assertEqual(pluggy.confidence, "high")
        self.assertEqual(pluggy.matched_rule, "user_rule:1")

        system = classify_input(
            ClassificationInput(
                description="refund ifood",
                pluggy_merchant="ifood",
                amount=Decimal("-10"),
                user_rules=(rule,),
            )
        )
        self.assertEqual(system.internal_category, "Compras")
        self.assertEqual(system.source, "user_rule")

        fallback = classify_input(
            ClassificationInput(
                pluggy_merchant="ifood",
                amount=Decimal("-10"),
                user_rules=(rule,),
            )
        )
        self.assertEqual(fallback.internal_category, "Compras")
        self.assertEqual(fallback.source, "user_rule")

    def test_account_scopes_are_respected(self):
        credit_rule = user_rule(
            rule_id=1,
            account_type_scope="CREDIT",
            match_description="netflix",
            target_internal_category="Assinaturas",
        )
        bank_rule = user_rule(
            rule_id=2,
            account_type_scope="BANK",
            match_description="netflix",
            target_internal_category="Outros",
        )
        all_rule = user_rule(
            rule_id=3,
            account_type_scope="ALL",
            match_description="spotify",
            target_internal_category="Assinaturas",
        )

        credit = classify_input(
            ClassificationInput(
                description="NETFLIX.COM",
                amount=Decimal("-55"),
                account_type="CREDIT",
                user_rules=(credit_rule, bank_rule),
            )
        )
        bank = classify_input(
            ClassificationInput(
                description="NETFLIX.COM",
                amount=Decimal("-55"),
                account_type="BANK",
                user_rules=(credit_rule, bank_rule),
            )
        )
        all_credit = classify_input(
            ClassificationInput(
                description="SPOTIFY",
                amount=Decimal("-22"),
                account_type="CREDIT",
                user_rules=(all_rule,),
            )
        )
        all_bank = classify_input(
            ClassificationInput(
                description="SPOTIFY",
                amount=Decimal("-22"),
                account_type="BANK",
                user_rules=(all_rule,),
            )
        )

        self.assertEqual(credit.matched_rule, "user_rule:1")
        self.assertEqual(bank.matched_rule, "user_rule:2")
        self.assertEqual(all_credit.matched_rule, "user_rule:3")
        self.assertEqual(all_bank.matched_rule, "user_rule:3")

    def test_matching_modes_and_priority(self):
        low_priority = user_rule(
            rule_id=10,
            priority=100,
            match_description="mercado",
            target_internal_category="Compras",
        )
        high_priority = user_rule(
            rule_id=11,
            priority=1,
            match_description="mercado",
            target_internal_category="Alimentação",
        )
        result = classify_input(
            ClassificationInput(
                description="MERCADO CENTRAL",
                pluggy_raw_category="Food-and_drinks",
                pluggy_raw_subcategory="Online Courses",
                pluggy_raw_type="DEBIT",
                pluggy_merchant="Loja Petlove",
                amount=Decimal("-99"),
                user_rules=(high_priority, low_priority),
            )
        )
        self.assertEqual(result.matched_rule, "user_rule:11")
        self.assertEqual(result.internal_category, "Alimentação")

        category = classify_input(
            ClassificationInput(
                pluggy_raw_category="Food-and_drinks",
                amount=Decimal("-1"),
                user_rules=(user_rule(match_pluggy_category="food and drinks"),),
            )
        )
        subcategory = classify_input(
            ClassificationInput(
                pluggy_raw_subcategory="Online-Courses",
                amount=Decimal("-1"),
                user_rules=(user_rule(match_pluggy_subcategory="online courses"),),
            )
        )
        raw_type = classify_input(
            ClassificationInput(
                pluggy_raw_type="DEBIT",
                amount=Decimal("-1"),
                user_rules=(user_rule(match_pluggy_type="debit"),),
            )
        )
        merchant = classify_input(
            ClassificationInput(
                pluggy_merchant="COBASI CANOAS",
                amount=Decimal("-1"),
                user_rules=(user_rule(match_merchant="cobasi"),),
            )
        )
        positive = classify_input(
            ClassificationInput(
                description="bonus",
                amount=Decimal("100"),
                user_rules=(user_rule(match_description="bonus", match_amount_sign="positive"),),
            )
        )
        negative_miss = classify_input(
            ClassificationInput(
                description="bonus",
                amount=Decimal("-100"),
                user_rules=(user_rule(match_description="bonus", match_amount_sign="positive"),),
            )
        )

        self.assertEqual(category.source, "user_rule")
        self.assertEqual(subcategory.source, "user_rule")
        self.assertEqual(raw_type.source, "user_rule")
        self.assertEqual(merchant.source, "user_rule")
        self.assertEqual(positive.source, "user_rule")
        self.assertNotEqual(negative_miss.source, "user_rule")


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

    def test_apply_changes_only_classification_and_reports_outros_transitions(self):
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
                # Persisted as Outros by the pre-10D-B.2 rules; the new
                # "Sports goods" rule now classifies it as Compras.
                session.add(
                    Transaction(
                        id="tx-sports",
                        account_id="acc-1",
                        date=date(2026, 6, 1),
                        amount=Decimal("-90.00"),
                        description="DECATHLON 06/06",
                        pluggy_raw_category="Sports goods",
                        pluggy_raw_subcategory="Outdoor",
                        pluggy_raw_type="DEBIT",
                        pluggy_merchant="Decathlon",
                        internal_category="Outros",
                        cashflow_type="expense",
                        classification_source="fallback",
                        classification_confidence="low",
                        classification_rule_key="amount_sign:nonzero",
                        ignored_from_totals=False,
                    )
                )
                # Genuinely unknown: stays in the Outros fallback.
                session.add(
                    Transaction(
                        id="tx-empty",
                        account_id="acc-1",
                        date=date(2026, 6, 2),
                        amount=Decimal("-15.00"),
                        description="Mystery charge",
                    )
                )
                session.commit()

            result = reclassify(f"sqlite:///{db_path}", apply=True)
            self.assertEqual(result["no_longer_outros"], 1)
            self.assertEqual(result["still_outros"], 1)

            with Session(engine) as session:
                tx = session.get(Transaction, "tx-sports")
                self.assertEqual(tx.internal_category, "Compras")
                self.assertEqual(tx.classification_source, "pluggy_rule")
                # Raw Pluggy and financial fields must be untouched.
                self.assertEqual(tx.pluggy_raw_category, "Sports goods")
                self.assertEqual(tx.pluggy_raw_subcategory, "Outdoor")
                self.assertEqual(tx.pluggy_raw_type, "DEBIT")
                self.assertEqual(tx.pluggy_merchant, "Decathlon")
                self.assertEqual(tx.amount, Decimal("-90.00"))
                self.assertEqual(tx.description, "DECATHLON 06/06")
                unknown = session.get(Transaction, "tx-empty")
                self.assertEqual(unknown.internal_category, "Outros")
                self.assertEqual(unknown.classification_source, "fallback")


class UserClassificationRulesApiAndScriptTest(unittest.TestCase):
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

    def _seed_transactions(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=1, status="UPDATED"))
            session.add(Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT"))
            session.add(Account(id="bank-1", item_id="item-1", name="Bank", type="BANK"))
            session.add(
                Transaction(
                    id="tx-card",
                    account_id="credit-1",
                    date=date(2026, 6, 1),
                    amount=Decimal("-80.00"),
                    description="Cobasi Pet",
                    pluggy_raw_category="Shopping",
                    pluggy_raw_subcategory="Pet Supplies",
                    pluggy_raw_type="DEBIT",
                    pluggy_merchant="COBASI CANOAS",
                )
            )
            session.add(
                Transaction(
                    id="tx-bank",
                    account_id="bank-1",
                    date=date(2026, 6, 2),
                    amount=Decimal("-120.00"),
                    description="PIX Cobasi",
                    pluggy_raw_category="Transfer - PIX",
                    pluggy_raw_type="DEBIT",
                    pluggy_merchant="COBASI CANOAS",
                )
            )
            session.add(
                Transaction(
                    id="tx-manual",
                    account_id="credit-1",
                    date=date(2026, 6, 3),
                    amount=Decimal("-30.00"),
                    description="Cobasi manual",
                    pluggy_raw_category="Shopping",
                    pluggy_merchant="COBASI CANOAS",
                    internal_category="Compras",
                    cashflow_type="expense",
                    classification_source="manual_override",
                    classification_confidence="high",
                    classification_rule_key="manual_override:transaction",
                    ignored_from_totals=False,
                    is_user_overridden=True,
                )
            )
            session.commit()

    def test_crud_preview_and_compilation(self):
        self._seed_transactions()
        payload = {
            "name": "Cobasi credit as Pet",
            "priority": 10,
            "account_type_scope": "CREDIT",
            "match_merchant": "cobasi",
            "target_internal_category": "Pet",
            "target_cashflow_type": "expense",
        }
        created = self.client.post("/transactions/classification-rules", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        rule = created.json()
        self.assertEqual(rule["account_type_scope"], "CREDIT")
        self.assertEqual(rule["affected_count"], 1)

        preview = self.client.post(
            f"/transactions/classification-rules/{rule['id']}/preview",
            json={"match_description": "Cobasi"},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertEqual(body["matched_count"], 1)
        self.assertEqual(body["examples"][0]["current_internal_category"], "Compras")
        self.assertEqual(body["examples"][0]["new_internal_category"], "Pet")

        listed = self.client.get("/transactions/classification-rules")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], rule["id"])

        patched = self.client.patch(
            f"/transactions/classification-rules/{rule['id']}",
            json={"enabled": False},
        )
        self.assertEqual(patched.status_code, 200)
        with Session(self.engine) as session:
            self.assertEqual(load_compiled_user_rules(session), ())

        deleted = self.client.delete(f"/transactions/classification-rules/{rule['id']}")
        self.assertEqual(deleted.status_code, 204)
        missing = self.client.delete(f"/transactions/classification-rules/{rule['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_validation_rejects_invalid_or_matchless_rules(self):
        invalid = self.client.post(
            "/transactions/classification-rules",
            json={
                "name": "Invalid",
                "target_internal_category": "Nova categoria",
                "target_cashflow_type": "expense",
                "match_description": "x",
            },
        )
        self.assertEqual(invalid.status_code, 400)

        matchless = self.client.post(
            "/transactions/classification-rules",
            json={
                "name": "Matchless",
                "target_internal_category": "Outros",
                "target_cashflow_type": "expense",
            },
        )
        self.assertEqual(matchless.status_code, 400)

    def test_user_rule_reclassify_dry_run_and_apply_are_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "user-rules.db"
            engine = create_engine(f"sqlite:///{db_path}")
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Item(id="item-1", connector_id=1, status="UPDATED"))
                session.add(
                    Account(
                        id="credit-1",
                        item_id="item-1",
                        name="Card",
                        type="CREDIT",
                    )
                )
                session.add(
                    UserClassificationRule(
                        name="Cobasi as Pet",
                        priority=1,
                        account_type_scope="CREDIT",
                        match_merchant="cobasi",
                        target_internal_category="Pet",
                        target_cashflow_type="expense",
                    )
                )
                session.add(
                    Transaction(
                        id="tx-apply",
                        account_id="credit-1",
                        date=date(2026, 6, 1),
                        amount=Decimal("-80.00"),
                        description="Compra pet",
                        pluggy_raw_category="Shopping",
                        pluggy_raw_subcategory="Pet Supplies",
                        pluggy_raw_type="DEBIT",
                        pluggy_merchant="COBASI CANOAS",
                        internal_category="Compras",
                        cashflow_type="expense",
                        classification_source="pluggy_rule",
                        classification_confidence="high",
                        classification_rule_key="pluggy_raw_category:Shopping",
                        ignored_from_totals=False,
                    )
                )
                session.add(
                    Transaction(
                        id="tx-skip",
                        account_id="credit-1",
                        date=date(2026, 6, 2),
                        amount=Decimal("-30.00"),
                        description="Compra pet manual",
                        pluggy_raw_category="Shopping",
                        pluggy_merchant="COBASI CANOAS",
                        internal_category="Compras",
                        cashflow_type="expense",
                        classification_source="manual_override",
                        classification_confidence="high",
                        classification_rule_key="manual_override:transaction",
                        ignored_from_totals=False,
                        is_user_overridden=True,
                    )
                )
                session.commit()

            dry = reclassify_user_rules(f"sqlite:///{db_path}", apply=False)
            self.assertEqual(dry["mode"], "dry-run")
            self.assertEqual(dry["would_change"], 1)
            self.assertEqual(dry["changed"], 0)
            self.assertEqual(dry["skipped_overrides"], 1)

            with Session(engine) as session:
                tx = session.get(Transaction, "tx-apply")
                self.assertEqual(tx.internal_category, "Compras")

            applied = reclassify_user_rules(f"sqlite:///{db_path}", apply=True)
            self.assertEqual(applied["changed"], 1)
            self.assertEqual(applied["matched_by_rule"]["user_rule:1"], 1)
            with Session(engine) as session:
                tx = session.get(Transaction, "tx-apply")
                self.assertEqual(tx.internal_category, "Pet")
                self.assertEqual(tx.cashflow_type, "expense")
                self.assertEqual(tx.classification_source, "user_rule")
                self.assertEqual(tx.classification_rule_key, "user_rule:1")
                self.assertEqual(tx.pluggy_raw_category, "Shopping")
                self.assertEqual(tx.pluggy_raw_subcategory, "Pet Supplies")
                self.assertEqual(tx.pluggy_raw_type, "DEBIT")
                self.assertEqual(tx.pluggy_merchant, "COBASI CANOAS")
                self.assertEqual(tx.amount, Decimal("-80.00"))
                self.assertEqual(tx.description, "Compra pet")

                skipped = session.get(Transaction, "tx-skip")
                self.assertEqual(skipped.internal_category, "Compras")
                self.assertEqual(skipped.classification_source, "manual_override")


class TransferBankSlipClassificationLayerTest(unittest.TestCase):
    """Transfer - Bank Slip must route to BANK_OUTFLOW, not INTERNAL_TRANSFER."""

    def _make_classifier(self, accounts_by_id):
        return TransactionClassifier(
            accounts_by_id=accounts_by_id,
            ignored_patterns=[],
            bank_income_rules=[],
            bank_cashflow_rules=[],
        )

    def test_bank_slip_outflow_is_bank_outflow_not_internal_transfer(self):
        # A boleto payment (negative BANK, Transfer - Bank Slip) must appear
        # in cashflow as BANK_OUTFLOW. It must never become INTERNAL_TRANSFER,
        # which would set cashflow_excluded=True and hide the real expense.
        account = Account(id="bank-1", item_id="item-1", name="Checking", type="BANK")
        tx = Transaction(
            id="tx-boleto",
            account_id="bank-1",
            date=date(2026, 6, 10),
            amount=Decimal("-1200.00"),
            description="Aluguel via boleto",
            pluggy_raw_category="Transfer - Bank Slip",
            cashflow_type="expense",
            internal_category="Outros",
            classification_source="pluggy_rule",
            classification_confidence="medium",
            classification_rule_key="pluggy_raw_category:Transfer - Bank Slip",
            ignored_from_totals=False,
        )
        classifier = self._make_classifier({"bank-1": account})
        result = classifier.classify(tx)
        self.assertEqual(result.kind, TransactionKind.BANK_OUTFLOW)
        self.assertFalse(result.cashflow_excluded)

    def test_bank_slip_inflow_is_bank_income_excluded_from_receitas(self):
        # Positive BANK Transfer - Bank Slip is real cash flow, but must NOT
        # appear as Receitas. bank_income_excluded must be True.
        account = Account(id="bank-1", item_id="item-1", name="Checking", type="BANK")
        tx = Transaction(
            id="tx-boleto-in",
            account_id="bank-1",
            date=date(2026, 6, 10),
            amount=Decimal("500.00"),
            description="Boleto recebido",
            pluggy_raw_category="Transfer - Bank Slip",
            cashflow_type="expense",
            internal_category="Outros",
            classification_source="pluggy_rule",
            classification_confidence="medium",
            classification_rule_key="pluggy_raw_category:Transfer - Bank Slip",
            ignored_from_totals=False,
        )
        classifier = self._make_classifier({"bank-1": account})
        result = classifier.classify(tx)
        self.assertEqual(result.kind, TransactionKind.BANK_INCOME)
        self.assertTrue(result.bank_income_excluded)
        self.assertFalse(result.cashflow_excluded)

    def test_transfer_internal_remains_internal_transfer(self):
        # Transfer - Internal is a real account-to-account movement; it must
        # still become INTERNAL_TRANSFER (cashflow_excluded=True).
        account = Account(id="bank-1", item_id="item-1", name="Checking", type="BANK")
        tx = Transaction(
            id="tx-internal",
            account_id="bank-1",
            date=date(2026, 6, 10),
            amount=Decimal("-3000.00"),
            description="TED conta poupança",
            pluggy_raw_category="Transfer - Internal",
            cashflow_type="transfer",
            internal_category="Transferências",
            classification_source="pluggy_rule",
            classification_confidence="high",
            classification_rule_key="pluggy_raw_category:Transfer - Internal",
            ignored_from_totals=True,
        )
        classifier = self._make_classifier({"bank-1": account})
        result = classifier.classify(tx)
        self.assertEqual(result.kind, TransactionKind.INTERNAL_TRANSFER)
        self.assertTrue(result.cashflow_excluded)

    def test_credit_transfer_override_is_not_card_purchase(self):
        account = Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT")
        tx = Transaction(
            id="tx-credit-transfer",
            account_id="credit-1",
            date=date(2026, 6, 10),
            amount=Decimal("-300.00"),
            description="Transferencia no cartao",
            pluggy_raw_category="Shopping",
            cashflow_type="transfer",
            internal_category="Transferências",
            classification_source="manual_override",
            classification_confidence="high",
            classification_rule_key="manual_override",
            ignored_from_totals=True,
            is_user_overridden=True,
        )
        classifier = self._make_classifier({"credit-1": account})
        result = classifier.classify(tx)
        self.assertFalse(result.is_card_purchase)
        self.assertEqual(result.kind, TransactionKind.IGNORED)

    def test_credit_refund_classification_is_not_card_purchase(self):
        account = Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT")
        tx = Transaction(
            id="tx-credit-refund",
            account_id="credit-1",
            date=date(2026, 6, 10),
            amount=Decimal("-80.00"),
            description="Estorno compra",
            pluggy_raw_category="Refund",
            cashflow_type="refund",
            internal_category="Estorno",
            classification_source="pluggy_rule",
            classification_confidence="high",
            classification_rule_key="pluggy_raw_category:Refund",
            ignored_from_totals=False,
        )
        classifier = self._make_classifier({"credit-1": account})
        result = classifier.classify(tx)
        self.assertFalse(result.is_card_purchase)
        self.assertEqual(result.kind, TransactionKind.OTHER)


class CreditPurchaseScopeTest(unittest.TestCase):
    """PIX/bank movements must never enter the CREDIT purchase breakdown."""

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
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=1, status="UPDATED"))
            session.add(Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT"))
            session.add(Account(id="bank-1", item_id="item-1", name="Checking", type="BANK"))
            session.add(
                Transaction(
                    id="tx-card-food",
                    account_id="credit-1",
                    date=self.today,
                    amount=Decimal("-80.00"),
                    description="Restaurante",
                    pluggy_raw_category="Eating out",
                )
            )
            session.add(
                Transaction(
                    id="tx-bank-pix",
                    account_id="bank-1",
                    date=self.today,
                    amount=Decimal("-900.00"),
                    description="Pix enviado Fulano",
                    pluggy_raw_category="Transfer - PIX",
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_monthly_stats_only_include_credit_purchases(self):
        body = self.client.get("/stats/monthly").json()
        names = {item["name"] for item in body["categories"]}
        self.assertIn("Alimentação", names)
        self.assertNotIn("Transferências", names)
        total = sum(month["total"] for month in body["months"])
        self.assertAlmostEqual(total, 80.0)

    def test_monthly_stats_uses_resolved_credit_category(self):
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-card-shopping",
                    account_id="credit-1",
                    date=self.today,
                    amount=Decimal("-120.00"),
                    description="Manual pet mas raw shopping",
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

        body = self.client.get("/stats/monthly").json()
        by_name = {item["name"]: item for item in body["categories"]}
        self.assertIn("Compras pessoais", by_name)
        self.assertNotIn("Pet", by_name)
        self.assertAlmostEqual(by_name["Compras pessoais"]["total"], 120.0)

    def test_stats_summary_excludes_bank_pix(self):
        body = self.client.get("/stats").json()
        self.assertAlmostEqual(body["total_spent"], 80.0)

    def test_bank_rule_still_does_not_enter_credit_purchase_breakdown(self):
        with Session(self.engine) as session:
            session.add(
                UserClassificationRule(
                    name="PIX as purchases",
                    priority=1,
                    account_type_scope="BANK",
                    match_description="pix enviado",
                    target_internal_category="Compras",
                    target_cashflow_type="expense",
                )
            )
            session.commit()

        body = self.client.get("/stats/monthly").json()
        names = {item["name"] for item in body["categories"]}
        self.assertIn("Alimentação", names)
        self.assertNotIn("Compras", names)
        total = sum(month["total"] for month in body["months"])
        self.assertAlmostEqual(total, 80.0)


if __name__ == "__main__":
    unittest.main()
