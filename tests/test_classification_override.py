import tempfile
import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, Item, Transaction
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.sync import upsert_transaction
from app.services.transaction_reports import invoice_summary
from app.services.transactions import credit_card_spend_transactions
from scripts.reclassify_transactions_v2 import reclassify


class ManualClassificationOverrideTest(unittest.TestCase):
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
        self._seed_base_data()

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed_base_data(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(Account(id="credit-1", item_id="item-1", name="Credit Card", type="CREDIT"))
            session.add(Account(id="bank-1", item_id="item-1", name="Checking", type="BANK"))
            session.add(
                Transaction(
                    id="tx-food",
                    account_id="credit-1",
                    date=self.today,
                    amount=Decimal("50.00"),
                    description="Padaria do bairro",
                    category="Food",
                    pluggy_raw_category="Food",
                    pluggy_raw_subcategory="Groceries",
                    pluggy_raw_type="DEBIT",
                    pluggy_merchant="Padaria",
                    internal_category="Alimentação",
                    cashflow_type="expense",
                    classification_source="pluggy_rule",
                    classification_confidence="high",
                    classification_rule_key="pluggy_raw_category:Food",
                    ignored_from_totals=False,
                )
            )
            # Legacy-style row: synced before 10D-B, classification fields empty.
            session.add(
                Transaction(
                    id="tx-unknown",
                    account_id="credit-1",
                    date=self.today,
                    amount=Decimal("30.00"),
                    description="Compra sem categoria",
                )
            )
            session.commit()

    def _get_tx(self, tx_id: str) -> Transaction:
        with Session(self.engine) as session:
            return session.get(Transaction, tx_id)

    # ── Apply override ───────────────────────────────────────────────

    def test_apply_override_sets_manual_fields(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={
                "internal_category": "Transporte",
                "cashflow_type": "expense",
                "ignored_from_totals": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["internal_category"], "Transporte")
        self.assertEqual(body["cashflow_type"], "expense")
        self.assertEqual(body["classification_source"], "manual_override")
        self.assertEqual(body["classification_confidence"], "high")
        self.assertEqual(body["classification_rule_key"], "manual_override")
        self.assertTrue(body["is_user_overridden"])
        self.assertFalse(body["ignored_from_totals"])

        tx = self._get_tx("tx-food")
        self.assertEqual(tx.internal_category, "Transporte")
        self.assertTrue(tx.is_user_overridden)
        self.assertEqual(tx.classification_source, "manual_override")

    def test_apply_override_preserves_raw_pluggy_and_financial_fields(self):
        self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Lazer", "cashflow_type": "expense"},
        )
        tx = self._get_tx("tx-food")
        self.assertEqual(tx.pluggy_raw_category, "Food")
        self.assertEqual(tx.pluggy_raw_subcategory, "Groceries")
        self.assertEqual(tx.pluggy_raw_type, "DEBIT")
        self.assertEqual(tx.pluggy_merchant, "Padaria")
        self.assertEqual(tx.category, "Food")
        self.assertEqual(tx.amount, Decimal("50.00"))
        self.assertEqual(tx.date, self.today)
        self.assertEqual(tx.description, "Padaria do bairro")
        self.assertEqual(tx.account_id, "credit-1")

    def test_apply_override_derives_ignored_from_cashflow_type(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Transferências", "cashflow_type": "transfer"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored_from_totals"])
        self.assertTrue(self._get_tx("tx-food").ignored_from_totals)

    def test_apply_override_accepts_explicit_ignored_flag(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={
                "internal_category": "Alimentação",
                "cashflow_type": "expense",
                "ignored_from_totals": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored_from_totals"])
        self.assertTrue(self._get_tx("tx-food").ignored_from_totals)

    def test_apply_override_rejects_invalid_category(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Categoria Inventada", "cashflow_type": "expense"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._get_tx("tx-food").is_user_overridden)

    def test_apply_override_normalizes_removed_category_alias(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Compras pessoais", "cashflow_type": "expense"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["internal_category"], "Outros")
        self.assertEqual(self._get_tx("tx-food").internal_category, "Outros")

    def test_apply_override_rejects_invalid_cashflow_type(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Alimentação", "cashflow_type": "magic"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._get_tx("tx-food").is_user_overridden)

    def test_apply_override_unknown_transaction_returns_404(self):
        response = self.client.patch(
            "/transactions/tx-missing/classification",
            json={"internal_category": "Alimentação", "cashflow_type": "expense"},
        )
        self.assertEqual(response.status_code, 404)

    def test_override_response_has_no_legacy_category_id(self):
        response = self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Alimentação", "cashflow_type": "expense"},
        )
        self.assertNotIn("category_id", response.json())

    # ── Reset override ───────────────────────────────────────────────

    def test_reset_restores_automatic_classification(self):
        self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Transporte", "cashflow_type": "expense"},
        )
        response = self.client.delete("/transactions/tx-food/classification-override")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["is_user_overridden"])
        self.assertEqual(body["internal_category"], "Alimentação")
        self.assertEqual(body["classification_source"], "pluggy_rule")
        tx = self._get_tx("tx-food")
        self.assertFalse(tx.is_user_overridden)
        self.assertEqual(tx.internal_category, "Alimentação")

    def test_reset_uses_new_layer_fallback_for_unknown(self):
        self.client.patch(
            "/transactions/tx-unknown/classification",
            json={"internal_category": "Lazer", "cashflow_type": "expense"},
        )
        response = self.client.delete("/transactions/tx-unknown/classification-override")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["internal_category"], "Outros")
        self.assertEqual(body["classification_source"], "fallback")
        self.assertEqual(body["classification_confidence"], "low")
        self.assertFalse(body["is_user_overridden"])

    def test_reset_unknown_transaction_returns_404(self):
        response = self.client.delete("/transactions/tx-missing/classification-override")
        self.assertEqual(response.status_code, 404)

    # ── Options endpoint ─────────────────────────────────────────────

    def test_classification_options_endpoint(self):
        response = self.client.get("/transactions/classification-options")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("Alimentação", body["internal_categories"])
        self.assertIn("Outros", body["internal_categories"])
        self.assertIn("expense", body["cashflow_types"])
        self.assertTrue(body["suggested_ignored_from_totals"]["transfer"])
        self.assertFalse(body["suggested_ignored_from_totals"]["expense"])

    # ── Protection against automatic reclassification ────────────────

    def test_sync_upsert_does_not_overwrite_manual_override(self):
        self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Pet", "cashflow_type": "expense"},
        )
        raw_tx = {
            "id": "tx-food",
            "date": self.today.isoformat(),
            "amount": "50.00",
            "description": "Padaria do bairro",
            "category": "Food",
        }
        with Session(self.engine) as session:
            upsert_transaction(raw_tx, "credit-1", session, account_type="CREDIT")
            session.commit()
        tx = self._get_tx("tx-food")
        self.assertTrue(tx.is_user_overridden)
        self.assertEqual(tx.internal_category, "Pet")
        self.assertEqual(tx.classification_source, "manual_override")

    def test_reclassify_script_skips_manual_overrides(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_url = f"sqlite:///{tmp_dir}/test.db"
            engine = create_engine(database_url)
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
                session.add(Account(id="credit-1", item_id="item-1", name="Card", type="CREDIT"))
                session.add(
                    Transaction(
                        id="tx-manual",
                        account_id="credit-1",
                        date=self.today,
                        amount=Decimal("-10.00"),
                        description="Manual",
                        pluggy_raw_category="Food",
                        internal_category="Pet",
                        cashflow_type="expense",
                        classification_source="manual_override",
                        classification_confidence="high",
                        classification_rule_key="manual_override",
                        is_user_overridden=True,
                        ignored_from_totals=False,
                    )
                )
                session.add(
                    Transaction(
                        id="tx-auto",
                        account_id="credit-1",
                        date=self.today,
                        amount=Decimal("-20.00"),
                        description="Restaurante",
                        category="Food",
                    )
                )
                session.commit()

            result = reclassify(database_url, apply=True)
            self.assertEqual(result["skipped_overrides"], 1)

            with Session(engine) as session:
                manual = session.get(Transaction, "tx-manual")
                self.assertEqual(manual.internal_category, "Pet")
                self.assertEqual(manual.classification_source, "manual_override")
                self.assertTrue(manual.is_user_overridden)
                auto = session.get(Transaction, "tx-auto")
                self.assertEqual(auto.internal_category, "Alimentação")

    # ── Serialization on history/dashboard endpoints ──────────────────

    def test_transactions_endpoint_serializes_override_fields(self):
        self.client.patch(
            "/transactions/tx-food/classification",
            json={"internal_category": "Pet", "cashflow_type": "expense"},
        )
        response = self.client.get("/transactions", params={"account_type": "CREDIT"})
        self.assertEqual(response.status_code, 200)
        by_id = {tx["id"]: tx for tx in response.json()}
        tx = by_id["tx-food"]
        self.assertTrue(tx["is_user_overridden"])
        self.assertEqual(tx["internal_category"], "Pet")
        self.assertEqual(tx["classification_source"], "manual_override")
        self.assertEqual(tx["pluggy_raw_category"], "Food")

    def test_monthly_stats_respects_manual_override(self):
        before = self.client.get("/stats/monthly").json()
        before_names = {item["name"] for item in before["categories"]}
        self.assertIn("Alimentação", before_names)

        # Pin the only Alimentação expense out of the totals.
        self.client.patch(
            "/transactions/tx-food/classification",
            json={
                "internal_category": "Transferências",
                "cashflow_type": "transfer",
                "ignored_from_totals": True,
            },
        )
        after = self.client.get("/stats/monthly").json()
        after_names = {item["name"] for item in after["categories"]}
        self.assertNotIn("Alimentação", after_names)
        self.assertNotIn("Transferências", after_names)

    def test_card_invoice_aggregates_respect_manual_transfer_override(self):
        before = self.client.get("/stats").json()
        self.assertAlmostEqual(before["invoice_open_total"], 80.0, places=2)

        self.client.patch(
            "/transactions/tx-food/classification",
            json={
                "internal_category": "Transferências",
                "cashflow_type": "transfer",
                "ignored_from_totals": True,
            },
        )

        with Session(self.engine) as session:
            invoice = invoice_summary(
                session,
                to_date=self.today,
            )
            card_spend = credit_card_spend_transactions(
                session,
                self.today,
                self.today,
            )

        self.assertAlmostEqual(invoice["invoice_open_total"], 30.0, places=2)
        self.assertNotIn("tx-food", {tx.id for tx in card_spend})
        self.assertIn("tx-unknown", {tx.id for tx in card_spend})

    def test_planning_invoice_respects_manual_transfer_override(self):
        year_month = self.today.strftime("%Y-%m")

        with Session(self.engine) as session:
            before = planning_invoice_for_month(session, year_month, today=self.today)
        self.assertAlmostEqual(before["amount"], 80.0, places=2)
        self.assertEqual(before["source"], "open_invoice")

        self.client.patch(
            "/transactions/tx-food/classification",
            json={
                "internal_category": "Transferências",
                "cashflow_type": "transfer",
                "ignored_from_totals": True,
            },
        )

        with Session(self.engine) as session:
            after = planning_invoice_for_month(session, year_month, today=self.today)

        self.assertAlmostEqual(after["amount"], 30.0, places=2)
        self.assertEqual(after["source"], "open_invoice")


if __name__ == "__main__":
    unittest.main()
