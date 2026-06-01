import unittest
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import (
    Account,
    Budget,
    Category,
    CategoryRule,
    CreditCardBill,
    ExpectedIncome,
    Item,
    Transaction,
)


class FixedCostsTest(unittest.TestCase):
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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit",
                    type="CREDIT",
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_create_list_update_delete_fixed_costs(self):
        category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Moradia", "color": "#0ea5e9", "sort_order": 1},
        ).json()
        self.assertEqual(category["name"], "Moradia")

        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Aluguel",
                "amount": 2500,
                "due_day": 5,
            },
        ).json()
        self.assertEqual(cost["amount"], 2500.0)
        self.assertTrue(cost["active"])

        listed = self.client.get("/fixed-costs").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["category_name"], "Moradia")

        patched = self.client.patch(
            f"/fixed-costs/{cost['id']}",
            json={"amount": 2600, "active": False},
        ).json()
        self.assertEqual(patched["amount"], 2600.0)
        self.assertFalse(patched["active"])

        self.assertEqual(self.client.get("/fixed-costs").json(), [])
        all_rows = self.client.get(
            "/fixed-costs", params={"include_inactive": True}
        ).json()
        self.assertEqual(len(all_rows), 1)

        self.assertEqual(
            self.client.delete(f"/fixed-costs/{cost['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(
                f"/fixed-cost-categories/{category['id']}"
            ).status_code,
            204,
        )

    def test_monthly_breakdown_applies_override(self):
        category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Escola", "color": "#f97316"},
        ).json()
        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Mensalidade",
                "amount": 1800,
                "due_day": 10,
            },
        ).json()

        base = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(base["total"], 1800.0)
        self.assertFalse(base["entries"][0]["is_override"])

        override = self.client.put(
            f"/fixed-costs/{cost['id']}/overrides/2026-06",
            json={"amount": 1950},
        ).json()
        self.assertEqual(override["amount"], 1950.0)

        june = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        july = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-07"}
        ).json()
        self.assertEqual(june["total"], 1950.0)
        self.assertTrue(june["entries"][0]["is_override"])
        self.assertEqual(july["total"], 1800.0)

        self.assertEqual(
            self.client.delete(
                f"/fixed-costs/{cost['id']}/overrides/2026-06"
            ).status_code,
            204,
        )
        june_again = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(june_again["total"], 1800.0)

    def test_spending_capacity_combines_income_fixed_costs_and_invoice(self):
        with Session(self.engine) as session:
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-1",
                    name="Bank",
                    type="BANK",
                )
            )
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.add(
                Transaction(
                    id="tx-card-1",
                    account_id="credit-1",
                    date=date(2026, 5, 10),
                    amount=Decimal("1200"),
                    description="Compra",
                    category="Shopping",
                )
            )
            session.add(
                Transaction(
                    id="tx-card-2",
                    account_id="credit-1",
                    date=date(2026, 5, 11),
                    amount=Decimal("700"),
                    description="Posto de gasolina",
                    category="Fuel",
                )
            )
            session.add(
                Transaction(
                    id="tx-income-1",
                    account_id="bank-1",
                    date=date(2026, 5, 5),
                    amount=Decimal("6000"),
                    description="Recebimento salario",
                    category="Salary",
                )
            )
            session.add(Category(id=1, name="Mercado", color="#22c55e", sort_order=1))
            session.add(
                Category(id=2, name="Transporte", color="#f97316", sort_order=2)
            )
            session.add(CategoryRule(pluggy_category="Shopping", category_id=1))
            session.add(CategoryRule(pluggy_category="Fuel", category_id=2))
            session.add(Budget(category_id=1, monthly_target=Decimal("1500")))
            session.add(Budget(category_id=2, monthly_target=Decimal("500")))
            session.commit()

        category = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Condominio",
                "amount": 2000,
                "due_day": 8,
            },
        )

        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()

        self.assertEqual(capacity["expected_income_total"], 10000.0)
        self.assertEqual(capacity["receita_esperada"], 10000.0)
        self.assertEqual(capacity["received_income_total"], 6000.0)
        self.assertEqual(capacity["valor_recebido"], 6000.0)
        self.assertEqual(capacity["received_income_count"], 1)
        self.assertEqual(capacity["income_to_receive"], 4000.0)
        self.assertEqual(capacity["receita_a_receber"], 4000.0)
        self.assertEqual(capacity["income_over_expected"], 0.0)
        self.assertEqual(capacity["income_received_progress_pct"], 60.0)
        self.assertEqual(capacity["fixed_cost_total"], 2000.0)
        self.assertEqual(capacity["variable_budget_total"], 2000.0)
        self.assertEqual(capacity["variable_budget_spent"], 1900.0)
        self.assertEqual(capacity["variable_budget_consumed"], 1700.0)
        self.assertEqual(capacity["variable_budget_remaining"], 300.0)
        self.assertEqual(capacity["variable_budget_overage"], 200.0)
        self.assertEqual(capacity["variable_budget_free_impact"], 200.0)
        self.assertEqual(capacity["unbudgeted_variable_spent"], 0.0)
        self.assertEqual(capacity["planned_expense_total"], 4000.0)
        self.assertEqual(capacity["card_invoice_total"], 1900.0)
        self.assertEqual(capacity["card_invoice_gross_total"], 1900.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 1900.0)
        self.assertEqual(capacity["card_invoice_fixed_cost_total"], 0.0)
        self.assertEqual(capacity["planned_after_fixed_costs"], 8000.0)
        self.assertEqual(capacity["remaining_after_plan"], 6000.0)
        self.assertEqual(capacity["available_to_spend"], 6100.0)
        self.assertEqual(capacity["discretionary_available"], 6100.0)
        self.assertEqual(capacity["received_based_available_to_spend"], 2100.0)
        self.assertEqual(capacity["remaining_after_invoice"], 6100.0)
        self.assertEqual(capacity["remaining_after_plan_and_invoice"], 4100.0)
        # Sanity: the new invoice split sums to the legacy total.
        self.assertEqual(
            capacity["invoice_paid_total"] + capacity["invoice_open_total"],
            capacity["card_invoice_total"],
        )
        self.assertEqual(
            capacity["invoice_paid_gross_total"] + capacity["invoice_open_gross_total"],
            capacity["card_invoice_gross_total"],
        )

        variable_items = {
            item["category_name"]: item
            for item in capacity["variable_budgets"]["items"]
        }
        self.assertEqual(variable_items["Mercado"]["target_consumed"], 1200.0)
        self.assertEqual(variable_items["Mercado"]["remaining_target"], 300.0)
        self.assertEqual(variable_items["Mercado"]["overage"], 0.0)
        self.assertEqual(variable_items["Mercado"]["free_impact"], 0.0)
        self.assertEqual(variable_items["Transporte"]["target_consumed"], 500.0)
        self.assertEqual(variable_items["Transporte"]["remaining_target"], 0.0)
        self.assertEqual(variable_items["Transporte"]["overage"], 200.0)
        self.assertEqual(variable_items["Transporte"]["free_impact"], 200.0)

    def test_monthly_breakdown_marks_paid_when_transaction_matches(self):
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-internet",
                    account_id="credit-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("119.90"),
                    description="Internet Claro",
                    category="Telecommunications",
                )
            )
            session.commit()

        categories = self.client.get("/fixed-cost-categories").json()
        category = next(category for category in categories if category["name"] == "Internet")
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Internet",
                "amount": 120,
                "due_day": 10,
            },
        )

        breakdown = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-06"}
        ).json()

        entry = breakdown["entries"][0]
        self.assertEqual(entry["status"], "paid")
        self.assertEqual(entry["matched_transaction"]["id"], "tx-internet")

    def test_manual_fixed_cost_match_excludes_from_invoice_and_skips_variable_budget(self):
        with Session(self.engine) as session:
            session.add(Category(id=10, name="Saúde", color="#38bdf8", sort_order=1))
            session.add(CategoryRule(pluggy_category="Pharmacy", category_id=10))
            session.add(Budget(category_id=10, monthly_target=Decimal("1000")))
            session.add(
                Transaction(
                    id="tx-venvanse",
                    account_id="credit-1",
                    date=date(2026, 5, 12),
                    amount=Decimal("740.00"),
                    description="Farmacia Venvanse",
                    category="Pharmacy",
                )
            )
            # An unrelated card purchase that must remain in the invoice
            # total — only the fixed-cost-matched one should be excluded.
            session.add(
                Transaction(
                    id="tx-other",
                    account_id="credit-1",
                    date=date(2026, 5, 15),
                    amount=Decimal("260.00"),
                    description="Restaurante",
                    category="Food",
                )
            )
            session.commit()

        # Before any fixed cost exists, the pharmacy purchase is just a
        # regular variable expense.
        before = self.client.get(
            "/budgets/progress", params={"year_month": "2026-05"}
        ).json()
        before_items = {
            item["category_name"]: item for item in before["items"]
        }
        self.assertEqual(before_items["Saúde"]["projected_spent"], 740.0)

        fixed_category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Medicamento", "color": "#38bdf8"},
        ).json()
        fixed_cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": fixed_category["id"],
                "description": "Venvanse",
                "amount": 740,
                "due_day": 12,
            },
        ).json()

        # Auto-match already excludes the transaction from the variable
        # budget (description + amount overlap with the new fixed cost).
        after_auto = self.client.get(
            "/budgets/progress", params={"year_month": "2026-05"}
        ).json()
        after_auto_items = {
            item["category_name"]: item for item in after_auto["items"]
        }
        self.assertEqual(after_auto_items["Saúde"]["projected_spent"], 0.0)

        match = self.client.post(
            f"/fixed-costs/{fixed_cost['id']}/matches",
            json={"transaction_id": "tx-venvanse", "year_month": "2026-05"},
        ).json()

        self.assertEqual(match["fixed_cost_id"], fixed_cost["id"])
        self.assertEqual(match["transaction_id"], "tx-venvanse")
        self.assertEqual(match["year_month"], "2026-05")

        listed_matches = self.client.get(
            "/fixed-costs/matches", params={"year_month": "2026-05"}
        ).json()
        self.assertEqual(len(listed_matches), 1)
        self.assertEqual(listed_matches[0]["id"], match["id"])
        self.assertEqual(listed_matches[0]["transaction"]["id"], "tx-venvanse")

        breakdown = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-05"}
        ).json()
        entry = breakdown["entries"][0]
        self.assertEqual(entry["status"], "paid")
        self.assertEqual(entry["match_source"], "manual")
        self.assertEqual(entry["fixed_cost_transaction_match_id"], match["id"])
        self.assertEqual(entry["matched_transaction"]["id"], "tx-venvanse")

        progress = self.client.get(
            "/budgets/progress", params={"year_month": "2026-05"}
        ).json()
        progress_items = {
            item["category_name"]: item for item in progress["items"]
        }
        self.assertEqual(progress["summary"]["projected_spent"], 0.0)
        self.assertEqual(
            progress["summary"]["fixed_cost_matched_transaction_count"], 1
        )
        self.assertEqual(progress_items["Saúde"]["projected_spent"], 0.0)
        self.assertEqual(progress_items["Saúde"]["remaining_target"], 1000.0)

        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()
        # The R$ 740 pharmacy purchase is already counted as a fixed cost
        # (fixed_cost_total). It still belongs to the real card invoice
        # (gross), but must leave the planning invoice (discretionary) so
        # "remaining after invoice" does not double-subtract it.
        self.assertEqual(capacity["card_invoice_total"], 260.0)
        self.assertEqual(capacity["card_invoice_gross_total"], 1000.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 260.0)
        self.assertEqual(capacity["card_invoice_fixed_cost_total"], 740.0)
        self.assertEqual(capacity["invoice_open_total"], 260.0)
        self.assertEqual(capacity["invoice_open_gross_total"], 1000.0)
        self.assertEqual(capacity["invoice_open_discretionary_total"], 260.0)
        self.assertEqual(capacity["invoice_paid_total"], 0.0)
        self.assertEqual(capacity["fixed_cost_total"], 740.0)
        self.assertEqual(capacity["variable_budget_spent"], 0.0)
        self.assertEqual(capacity["variable_budget_remaining"], 1000.0)

    def test_manual_fixed_cost_match_reduces_discretionary_invoice_in_paid_mode(self):
        with Session(self.engine) as session:
            session.add(Category(id=11, name="Saúde", color="#38bdf8", sort_order=1))
            session.add(CategoryRule(pluggy_category="Pharmacy", category_id=11))
            session.add(Budget(category_id=11, monthly_target=Decimal("1000")))
            session.add_all(
                [
                    Transaction(
                        id="tx-paid-venvanse",
                        account_id="credit-1",
                        date=date(2026, 5, 12),
                        amount=Decimal("740.00"),
                        description="Farmacia Venvanse",
                        category="Pharmacy",
                    ),
                    Transaction(
                        id="tx-paid-invoice",
                        account_id="credit-1",
                        date=date(2026, 5, 20),
                        amount=Decimal("-1200.00"),
                        description="Pagamento recebido",
                        category="Credit card payment",
                    ),
                ]
            )
            session.commit()

        fixed_category = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Medicamento", "color": "#38bdf8"},
        ).json()
        fixed_cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": fixed_category["id"],
                "description": "Venvanse",
                "amount": 740,
                "due_day": 12,
            },
        ).json()
        self.client.post(
            f"/fixed-costs/{fixed_cost['id']}/matches",
            json={"transaction_id": "tx-paid-venvanse", "year_month": "2026-05"},
        )

        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()

        self.assertEqual(capacity["invoice_mode"], "paid")
        self.assertEqual(capacity["card_invoice_gross_total"], 1200.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 460.0)
        self.assertEqual(capacity["card_invoice_fixed_cost_total"], 740.0)
        self.assertEqual(capacity["invoice_paid_gross_total"], 1200.0)
        self.assertEqual(capacity["invoice_paid_discretionary_total"], 460.0)

    def test_link_unlink_fixed_cost_match_route(self):
        """POST /fixed-costs/{id}/matches links a transaction; DELETE /fixed-costs/matches/{id} removes it."""
        with Session(self.engine) as session:
            session.add(Account(id="bank-1", item_id="item-1", name="Conta", type="BANK"))
            # Amount and tokens deliberately differ from the fixed cost below so no auto-match fires.
            # |620-500|=120 > max(620*0.15, 10)=93 → outside tolerance; tokens: {"para","pessoa"} vs {"despesa","mensal"}
            session.add(
                Transaction(
                    id="tx-pix-out",
                    account_id="bank-1",
                    date=date(2026, 5, 8),
                    amount=Decimal("-500.00"),
                    description="PIX para pessoa",
                    category="Transfer",
                )
            )
            session.commit()

        cat = self.client.post(
            "/fixed-cost-categories", json={"name": "Familia", "color": "#8b5cf6"}
        ).json()
        cost = self.client.post(
            "/fixed-costs",
            json={"category_id": cat["id"], "description": "Despesa Mensal", "amount": 620, "due_day": 8},
        ).json()

        # Before linking: no manual match exists
        breakdown = self.client.get("/fixed-costs/by-month", params={"year_month": "2026-05"}).json()
        entry = next(e for e in breakdown["entries"] if e["fixed_cost_id"] == cost["id"])
        self.assertIsNone(entry["fixed_cost_transaction_match_id"])
        self.assertIsNone(entry["matched_transaction"])

        # Link: POST /fixed-costs/{id}/matches
        match = self.client.post(
            f"/fixed-costs/{cost['id']}/matches",
            json={"transaction_id": "tx-pix-out", "year_month": "2026-05"},
        ).json()
        self.assertEqual(match["fixed_cost_id"], cost["id"])
        self.assertEqual(match["transaction_id"], "tx-pix-out")
        self.assertEqual(match["year_month"], "2026-05")

        # After linking: status is paid, source is manual, match_id is set
        breakdown = self.client.get("/fixed-costs/by-month", params={"year_month": "2026-05"}).json()
        entry = next(e for e in breakdown["entries"] if e["fixed_cost_id"] == cost["id"])
        self.assertEqual(entry["status"], "paid")
        self.assertEqual(entry["match_source"], "manual")
        self.assertEqual(entry["fixed_cost_transaction_match_id"], match["id"])
        self.assertIsNotNone(entry["matched_transaction"])
        self.assertEqual(entry["matched_transaction"]["id"], "tx-pix-out")

        # The transaction is now accounted as a fixed cost
        capacity = self.client.get("/spending-capacity", params={"year_month": "2026-05"}).json()
        self.assertGreater(capacity["fixed_cost_actual_total"], 0)
        self.assertEqual(capacity["fixed_cost_actual_total"], 500.0)

        # GET matches endpoint also shows it
        matches_list = self.client.get("/fixed-costs/matches", params={"year_month": "2026-05"}).json()
        self.assertEqual(len(matches_list), 1)
        self.assertEqual(matches_list[0]["id"], match["id"])

        # Unlink: DELETE /fixed-costs/matches/{match_id}
        resp = self.client.delete(f"/fixed-costs/matches/{match['id']}")
        self.assertEqual(resp.status_code, 204)

        # After unlinking: no manual match, transaction is free again
        breakdown = self.client.get("/fixed-costs/by-month", params={"year_month": "2026-05"}).json()
        entry = next(e for e in breakdown["entries"] if e["fixed_cost_id"] == cost["id"])
        self.assertNotEqual(entry["status"], "paid")
        self.assertIsNone(entry["fixed_cost_transaction_match_id"])

        # Matches list is empty
        matches_list = self.client.get("/fixed-costs/matches", params={"year_month": "2026-05"}).json()
        self.assertEqual(len(matches_list), 0)

        # Deleting the same match again returns 404
        resp = self.client.delete(f"/fixed-costs/matches/{match['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_create_fixed_cost_from_transaction_uses_resolved_category(self):
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-condo",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("640.00"),
                    description="Condominio Edificio",
                    category="Housing",
                )
            )
            session.commit()

        response = self.client.post(
            "/fixed-costs/from-transaction",
            json={"transaction_id": "tx-condo", "description": "Condomínio"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["description"], "Condomínio")
        self.assertEqual(payload["amount"], 640.0)
        self.assertEqual(payload["due_day"], 8)
        self.assertEqual(payload["category_name"], "Condomínio")

    def test_templates_return_matching_category_ids(self):
        templates = self.client.get("/fixed-costs/templates").json()

        by_label = {template["label"]: template for template in templates}
        self.assertIsNotNone(by_label["Aluguel"]["category_id"])
        self.assertIsNotNone(by_label["Financiamento"]["category_id"])
        self.assertIsNotNone(by_label["Assinatura"]["category_id"])
        self.assertIsNotNone(by_label["Academia"]["category_id"])

    def test_validates_inputs(self):
        self.assertEqual(
            self.client.post(
                "/fixed-cost-categories", json={"name": ""}
            ).status_code,
            400,
        )

    def test_syncs_dedicated_default_categories(self):
        categories = self.client.get("/fixed-cost-categories").json()

        self.assertEqual(
            [
                "Aluguel",
                "Condomínio",
                "Financiamento",
                "Internet",
                "Luz",
                "Água",
                "Assinatura",
                "Pet",
                "Academia",
            ],
            [category["name"] for category in categories],
        )
        self.assertTrue(all(category["is_default"] for category in categories))
        self.assertEqual(
            self.client.delete(
                f"/fixed-cost-categories/{categories[0]['id']}"
            ).status_code,
            400,
        )

    def test_limits_custom_categories_to_five(self):
        for index in range(5):
            response = self.client.post(
                "/fixed-cost-categories",
                json={"name": f"Extra {index}", "color": "#64748b"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["is_default"])

        response = self.client.post(
            "/fixed-cost-categories",
            json={"name": "Extra 5", "color": "#64748b"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "custom category limit reached")
        self.assertEqual(
            self.client.post(
                "/fixed-costs",
                json={
                    "category_id": 999,
                    "description": "x",
                    "amount": -1,
                    "due_day": 1,
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/fixed-costs/by-month", params={"year_month": "bad"}
            ).status_code,
            400,
        )


class SpendingCapacityMonthlyShapeTest(unittest.TestCase):
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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-1",
                    name="Bank",
                    type="BANK",
                )
            )
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_spending_capacity_monthly_history_shape(self):
        response = self.client.get(
            "/spending-capacity/monthly",
            params={"months": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["month_count"], 1)
        row = payload["months"][0]
        self.assertIn("card_invoice_gross_total", row)
        self.assertIn("card_invoice_discretionary_total", row)
        self.assertIn("discretionary_available", row)
        self.assertIn("plan_status", row)
        self.assertIn("card_invoice_gross_total", payload["summary"])
        self.assertEqual(
            self.client.get(
                "/spending-capacity/monthly",
                params={"months": 25},
            ).status_code,
            400,
        )


class SpendingCapacityDiagnosticsTest(unittest.TestCase):
    """Covers #5 daily verba, #6 plan_status, #7 today injection, #8 installments."""

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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit",
                    type="CREDIT",
                )
            )
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_today_injection_makes_capacity_deterministic(self):
        """#7 — calling the service with an explicit `today` must override date.today()."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            # 31-day month (May 2026), pin today at the 11th.
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["days_remaining_in_month"], 21)  # 31 - 11 + 1

            # If today is BEFORE the month, full month of days.
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 4, 15)
            )
            self.assertEqual(capacity["days_remaining_in_month"], 31)

            # If today is AFTER the month, zero days remaining.
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 7, 1)
            )
            self.assertEqual(capacity["days_remaining_in_month"], 0)
            self.assertEqual(capacity["daily_discretionary_remaining"], 0.0)

    def test_daily_discretionary_remaining(self):
        """#5 — discretionary_available divided across days left in month."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            # Mid-month with no expenses → all R$ 10k spread across 21 days.
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["discretionary_available"], 10000.0)
            self.assertEqual(capacity["days_remaining_in_month"], 21)
            self.assertAlmostEqual(
                capacity["daily_discretionary_remaining"],
                10000.0 / 21,
                places=4,
            )

        # When discretionary goes negative, daily verba is clamped at 0
        # (you can't spend negative money per day). A fixed cost larger than
        # income pushes availability below zero.
        cat = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": cat["id"],
                "description": "Aluguel caro",
                "amount": 15000,
                "due_day": 10,
            },
        )
        from app.services.spending_capacity import spending_capacity_summary as cap

        with Session(self.engine) as session:
            capacity = cap(session, "2026-05", today=date(2026, 5, 11))
            self.assertLess(capacity["discretionary_available"], 0)
            self.assertEqual(capacity["daily_discretionary_remaining"], 0.0)

    def test_plan_status_flag_transitions(self):
        """#6 — healthy / tight / over based on the discretionary margin."""
        from app.services.spending_capacity import spending_capacity_summary

        # Healthy: no expenses, everything is discretionary
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "healthy")

        # Tight: a fixed cost eats >90% of income (margin under 10%)
        cat = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": cat["id"],
                "description": "Aluguel",
                "amount": 9500,
                "due_day": 10,
            },
        ).json()
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "tight")

        # Over: fixed cost exceeds income, discretionary goes negative
        self.client.patch(f"/fixed-costs/{cost['id']}", json={"amount": 12000})
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "over")

    def test_plan_status_unknown_when_no_income(self):
        """No expected income configured → can't grade the plan."""
        from app.services.spending_capacity import spending_capacity_summary
        from app.models import ExpectedIncome
        from sqlmodel import delete

        with Session(self.engine) as session:
            session.exec(delete(ExpectedIncome))
            session.commit()
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "unknown")

    def test_upcoming_months_projects_future_installments(self):
        """#8 — future-dated card purchases per month should be visible."""
        category = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Aluguel",
                "amount": 2000,
                "due_day": 5,
            },
        )

        # Three future installments landing across two months.
        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-parcela-1",
                        account_id="credit-1",
                        date=date(2026, 6, 10),
                        amount=Decimal("300"),
                        description="Notebook 3x parcela 1/3",
                        category="Electronics",
                    ),
                    Transaction(
                        id="tx-parcela-2",
                        account_id="credit-1",
                        date=date(2026, 7, 10),
                        amount=Decimal("300"),
                        description="Notebook 3x parcela 2/3",
                        category="Electronics",
                    ),
                    Transaction(
                        id="tx-parcela-3",
                        account_id="credit-1",
                        date=date(2026, 7, 15),
                        amount=Decimal("500"),
                        description="Curso 2x parcela 1/2",
                        category="Education",
                    ),
                ]
            )
            session.commit()

        from app.services.planning import upcoming_months

        with Session(self.engine) as session:
            months = upcoming_months(
                session, "2026-06", months=3, today=date(2026, 5, 31)
            )

        by_month = {m["year_month"]: m for m in months}
        # June: aluguel R$ 2000 + 1 parcela R$ 300
        self.assertEqual(by_month["2026-06"]["total"], 2000.0)
        self.assertEqual(by_month["2026-06"]["installments"]["total"], 300.0)
        self.assertEqual(by_month["2026-06"]["installments"]["count"], 1)
        self.assertEqual(by_month["2026-06"]["projected_total"], 2300.0)
        # July: aluguel R$ 2000 + 2 parcelas (300 + 500)
        self.assertEqual(by_month["2026-07"]["installments"]["total"], 800.0)
        self.assertEqual(by_month["2026-07"]["installments"]["count"], 2)
        self.assertEqual(by_month["2026-07"]["projected_total"], 2800.0)
        # August: just aluguel, no parcelas
        self.assertEqual(by_month["2026-08"]["installments"]["total"], 0.0)
        self.assertEqual(by_month["2026-08"]["installments"]["count"], 0)

    def test_installments_exclude_already_realized_transactions(self):
        """If today is past the transaction date, it isn't a future installment anymore."""
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-old-parcela",
                    account_id="credit-1",
                    date=date(2026, 5, 10),
                    amount=Decimal("400"),
                    description="Parcela antiga",
                    category="Electronics",
                )
            )
            session.commit()

        from app.services.credit_card_invoice import scheduled_installments_for_month

        with Session(self.engine) as session:
            # Today is AFTER the transaction → not a future installment
            summary = scheduled_installments_for_month(
                session, "2026-05", today=date(2026, 5, 20)
            )
            self.assertEqual(summary["total"], 0.0)

            # Today is BEFORE the transaction → it counts
            summary = scheduled_installments_for_month(
                session, "2026-05", today=date(2026, 5, 5)
            )
            self.assertEqual(summary["total"], 400.0)


class BankOutflowExcludesInvoicePaymentTest(unittest.TestCase):
    """bank_outflow_transactions must exclude credit-card invoice payments.

    When the user pays the invoice from the bank account, Pluggy records a
    BANK outflow with category "Credit card payment". That outflow must NOT
    appear in bank_outflows_total — the card charges are already captured
    in card_invoice_gross_total, so counting the bank payment would double-
    subtract the invoice amount.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(Account(id="bank-1", item_id="item-1", name="Bank", type="BANK"))
            session.add_all([
                # Regular PIX to a merchant — should be included
                Transaction(
                    id="tx-pix-mercado",
                    account_id="bank-1",
                    date=date(2026, 5, 10),
                    amount=Decimal("-350.00"),
                    description="PIX Mercado",
                    category="Supermarket",
                ),
                # Bank-side credit card invoice payment — must be EXCLUDED
                Transaction(
                    id="tx-fatura-bank",
                    account_id="bank-1",
                    date=date(2026, 5, 15),
                    amount=Decimal("-2500.00"),
                    description="Pagamento fatura cartao",
                    category="Credit card payment",
                ),
            ])
            session.commit()

    def test_invoice_payment_excluded_from_bank_outflows(self):
        from app.services.transactions import bank_outflow_transactions

        with Session(self.engine) as session:
            txs = bank_outflow_transactions(
                session,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 31),
            )
        ids = [tx.id for tx in txs]
        self.assertIn("tx-pix-mercado", ids)
        self.assertNotIn("tx-fatura-bank", ids)

    def test_bank_outflows_total_excludes_invoice_payment(self):
        from app.services.spending_capacity import spending_capacity_summary

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        try:
            with Session(self.engine) as session:
                capacity = spending_capacity_summary(
                    session, "2026-05", today=date(2026, 5, 31)
                )
            # Only the PIX (350) should appear — not the invoice payment (2500)
            self.assertAlmostEqual(capacity["bank_outflows_total"], 350.0, places=2)
        finally:
            app.dependency_overrides.clear()


class MonthlyPlanningAvailabilityTest(unittest.TestCase):
    """Regression suite for ``budget_available_to_spend``.

    Validates the headline number behaves like a real envelope: planned
    bills reserve cash before being paid, paid bills only move availability
    by their variance, category budgets are consumed per transaction (not
    via the invoice total), investment movements stay out of bank cash flow, and the
    monthly endpoint exposes the new field.
    """

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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add_all(
                [
                    Account(
                        id="credit-1",
                        item_id="item-1",
                        name="Credit",
                        type="CREDIT",
                    ),
                    Account(
                        id="bank-1",
                        item_id="item-1",
                        name="Bank",
                        type="BANK",
                    ),
                    ExpectedIncome(
                        description="Salario",
                        amount=Decimal("20300"),
                        expected_day=5,
                    ),
                ]
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    # ----- helpers -----

    def _make_water_fixed_cost(self, amount=300):
        category = self.client.post(
            "/fixed-cost-categories", json={"name": "Casa"}
        ).json()
        return self.client.post(
            "/fixed-costs",
            json={
                "category_id": category["id"],
                "description": "Conta de agua",
                "amount": amount,
                "due_day": 10,
            },
        ).json()

    def _capacity(self, year_month="2026-06"):
        return self.client.get(
            "/spending-capacity", params={"year_month": year_month}
        ).json()

    # ----- 1. Fixed cost pending -----

    def test_pending_fixed_cost_reserves_planned_amount(self):
        """Planned R$ 300 unpaid → R$ 300 reserved from availability."""
        self._make_water_fixed_cost(amount=300)

        capacity = self._capacity()

        self.assertEqual(capacity["fixed_cost_planned_total"], 300.0)
        self.assertEqual(capacity["fixed_cost_actual_total"], 0.0)
        self.assertEqual(capacity["fixed_cost_pending_total"], 300.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], 0.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 300.0)
        # 20300 - 300 = 20000
        self.assertEqual(capacity["budget_available_to_spend"], 20000.0)
        self.assertEqual(capacity["discretionary_available"], 20000.0)

    # ----- 2. Fixed cost paid exactly -----

    def test_paid_fixed_cost_same_availability_as_pending(self):
        """Planned R$ 300, paid R$ 300 → same availability as the pending case."""
        cost = self._make_water_fixed_cost(amount=300)
        pending_available = self._capacity()["budget_available_to_spend"]

        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-water-exact",
                    account_id="bank-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("-300"),
                    description="Conta de agua",
                    category="Utilities",
                )
            )
            session.commit()

        self.client.post(
            f"/fixed-costs/{cost['id']}/matches",
            json={"transaction_id": "tx-water-exact", "year_month": "2026-06"},
        )

        capacity = self._capacity()
        self.assertEqual(capacity["fixed_cost_actual_total"], 300.0)
        self.assertEqual(capacity["fixed_cost_pending_total"], 0.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], 0.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 300.0)
        self.assertEqual(
            capacity["budget_available_to_spend"], pending_available
        )

    # ----- 3. Fixed cost paid higher than planned -----

    def test_overshoot_only_reduces_availability_by_variance(self):
        """Current-month: planned R$ 300, paid R$ 370 → R$ 70 lower than pending.

        Uses today=2026-06-30 (current month) so the current-month formula branch
        (fixed_cost_reserved_total = actual paid) is exercised.
        """
        from app.services.spending_capacity import spending_capacity_summary

        cost = self._make_water_fixed_cost(amount=300)

        with Session(self.engine) as session:
            pending_available = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )["budget_available_to_spend"]

        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-water-over",
                    account_id="bank-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("-370"),
                    description="Conta de agua",
                    category="Utilities",
                )
            )
            session.commit()

        self.client.post(
            f"/fixed-costs/{cost['id']}/matches",
            json={"transaction_id": "tx-water-over", "year_month": "2026-06"},
        )

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        self.assertEqual(capacity["fixed_cost_actual_total"], 370.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], 70.0)
        self.assertEqual(capacity["fixed_cost_positive_variance_total"], 70.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 370.0)
        self.assertEqual(
            capacity["budget_available_to_spend"], pending_available - 70.0
        )

    # ----- 4. Fixed cost paid lower than planned -----

    def test_undershoot_releases_difference_back(self):
        """Current-month: planned R$ 300, paid R$ 270 → R$ 30 released back vs pending.

        Uses today=2026-06-30 (current month) so the current-month formula branch
        (fixed_cost_reserved_total = actual paid) is exercised.
        """
        from app.services.spending_capacity import spending_capacity_summary

        cost = self._make_water_fixed_cost(amount=300)

        with Session(self.engine) as session:
            pending_available = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )["budget_available_to_spend"]

        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-water-under",
                    account_id="bank-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("-270"),
                    description="Conta de agua",
                    category="Utilities",
                )
            )
            session.commit()

        self.client.post(
            f"/fixed-costs/{cost['id']}/matches",
            json={"transaction_id": "tx-water-under", "year_month": "2026-06"},
        )

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        self.assertEqual(capacity["fixed_cost_actual_total"], 270.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], -30.0)
        self.assertEqual(capacity["fixed_cost_negative_variance_total"], 30.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 270.0)
        self.assertEqual(
            capacity["budget_available_to_spend"], pending_available + 30.0
        )

    # ----- 5. Variable budget: only consumed reduces availability -----

    def test_variable_budget_only_consumed_part_reduces_availability(self):
        """Mercado planned R$ 1500, gasto R$ 430 → restam R$ 1070, disponível desce R$ 430.

        Uses 2026-07 (reliably future) so the future-month formula applies
        regardless of when today falls in June.
        """
        with Session(self.engine) as session:
            session.add(
                Category(id=1, name="Mercado", color="#22c55e", sort_order=1)
            )
            session.add(CategoryRule(pluggy_category="Supermarket", category_id=1))
            session.add(Budget(category_id=1, monthly_target=Decimal("1500")))
            session.add(
                Transaction(
                    id="tx-zaffari",
                    account_id="credit-1",
                    date=date(2026, 7, 4),
                    amount=Decimal("430.00"),
                    description="Zaffari",
                    category="Supermarket",
                )
            )
            session.commit()

        capacity = self._capacity("2026-07")
        self.assertEqual(capacity["variable_budget_total"], 1500.0)
        self.assertEqual(capacity["variable_budget_consumed"], 430.0)
        self.assertEqual(capacity["variable_budget_remaining"], 1070.0)
        self.assertEqual(capacity["variable_budget_overage"], 0.0)
        # Future month: variable_budget_total=1500 (full target, not just consumed=430).
        # tx-zaffari (430) is also picked up as a scheduled installment and subtracted.
        # 20300 - 1500 (variable_budget_total) - 430 (installment) = 18370
        self.assertEqual(capacity["budget_available_to_spend"], 18370.0)

    # ----- 6. Credit-card purchase not double-counted -----

    def test_credit_card_purchase_not_double_counted_via_invoice(self):
        """Card purchase consumes category; gross invoice tracks it but
        availability must NOT subtract the invoice again.

        Uses 2026-07 (reliably future) so the future-month formula applies.
        """
        with Session(self.engine) as session:
            session.add(
                Category(id=1, name="Mercado", color="#22c55e", sort_order=1)
            )
            session.add(CategoryRule(pluggy_category="Supermarket", category_id=1))
            session.add(Budget(category_id=1, monthly_target=Decimal("1500")))
            session.add(
                Transaction(
                    id="tx-zaffari",
                    account_id="credit-1",
                    date=date(2026, 7, 4),
                    amount=Decimal("430.00"),
                    description="Zaffari",
                    category="Supermarket",
                )
            )
            session.commit()

        capacity = self._capacity("2026-07")
        # Card invoice reflects the real R$ 430 charge
        self.assertEqual(capacity["card_invoice_gross_total"], 430.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 430.0)
        # For a future month the installment is subtracted BOTH as part of
        # variable_budget_total (full target=1500) and as a scheduled installment (430).
        # The invoice field is informational only and does NOT double-subtract.
        # 20300 - 1500 (variable_budget_total) - 430 (scheduled installment) = 18370
        self.assertEqual(capacity["budget_available_to_spend"], 18370.0)

    # ----- 7. Fixed cost on the credit card -----

    def test_fixed_cost_on_credit_card_not_double_counted(self):
        """A fixed-cost-matched card purchase belongs to:
        gross invoice, fixed cost actual; NOT discretionary invoice nor variable budget.

        Uses 2026-07 (reliably future) so the future-month formula applies.
        """
        with Session(self.engine) as session:
            session.add(
                Category(id=10, name="Saude", color="#38bdf8", sort_order=1)
            )
            session.add(CategoryRule(pluggy_category="Pharmacy", category_id=10))
            session.add(Budget(category_id=10, monthly_target=Decimal("1000")))
            session.add(
                Transaction(
                    id="tx-vyvanse",
                    account_id="credit-1",
                    date=date(2026, 7, 5),
                    amount=Decimal("740.00"),
                    description="Farmacia Vyvanse",
                    category="Pharmacy",
                )
            )
            session.commit()

        cost_category = self.client.post(
            "/fixed-cost-categories", json={"name": "Medicamento"}
        ).json()
        cost = self.client.post(
            "/fixed-costs",
            json={
                "category_id": cost_category["id"],
                "description": "Vyvanse",
                "amount": 740,
                "due_day": 5,
            },
        ).json()
        self.client.post(
            f"/fixed-costs/{cost['id']}/matches",
            json={"transaction_id": "tx-vyvanse", "year_month": "2026-07"},
        )

        capacity = self._capacity("2026-07")
        # In gross invoice but excluded from discretionary
        self.assertEqual(capacity["card_invoice_gross_total"], 740.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 0.0)
        self.assertEqual(capacity["card_invoice_fixed_cost_total"], 740.0)
        # Fixed cost actual = 740 (matched, on plan)
        self.assertEqual(capacity["fixed_cost_actual_total"], 740.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 740.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], 0.0)
        # Variable budget skipped the matched tx
        self.assertEqual(capacity["variable_budget_consumed"], 0.0)
        self.assertEqual(capacity["variable_budget_remaining"], 1000.0)
        # Future month: max(target=1000, consumed=0) = 1000; 20300 - 740 (fixed) - 1000 (var target) = 18560
        self.assertEqual(capacity["budget_available_to_spend"], 18560.0)

    # ----- 8. CDB / Fixed income stays out of bank flows -----

    def test_fixed_income_cdb_not_in_bank_flows_nor_available(self):
        """Pluggy "Fixed income" (CDB) movements:
        - do NOT appear in bank_outflows_total / bank_inflows_total
        - do NOT create active reserve/savings planning fields.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add_all(
                [
                    Transaction(
                        id="tx-cdb-out",
                        account_id="bank-1",
                        date=date(2026, 6, 5),
                        amount=Decimal("-1000"),
                        description="Aplicacao CDB",
                        category="Fixed income",
                    ),
                    Transaction(
                        id="tx-cdb-in",
                        account_id="bank-1",
                        date=date(2026, 6, 20),
                        amount=Decimal("200"),
                        description="Resgate CDB",
                        category="Fixed income",
                    ),
                ]
            )
            session.commit()

        # Pin today inside the month so the window captures the txs.
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )
        # Not in normal cash flows
        self.assertEqual(capacity["bank_outflows_total"], 0.0)
        self.assertEqual(capacity["bank_inflows_total"], 0.0)
        for field in (
            "reserva_application_total",
            "reserva_rescue_total",
            "reserve_applied_total",
            "reserve_target_total",
            "reserve_reserved_total",
            "available_after_reserve",
        ):
            self.assertNotIn(field, capacity)
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    # ----- 9. Auto-matched fixed cost must not double-count -----

    def test_auto_matched_fixed_cost_excluded_from_variable_budget(self):
        """A bank PIX that monthly_breakdown auto-matches to a fixed cost must
        NOT also leak into variable_budget_spent / unbudgeted_variable_spent.
        Otherwise it gets subtracted twice from budget_available_to_spend.

        Uses 2026-07 (reliably future) so the future-month formula applies.
        """
        cost = self._make_water_fixed_cost(amount=300)

        with Session(self.engine) as session:
            # Real-world setup: there IS a category mapping for the pluggy
            # category, so without explicit exclusion the PIX would consume
            # the "Casa variavel" envelope on top of the fixed cost.
            session.add(
                Category(id=50, name="Casa variavel", color="#0ea5e9", sort_order=1)
            )
            session.add(CategoryRule(pluggy_category="Utilities", category_id=50))
            session.add(Budget(category_id=50, monthly_target=Decimal("1000")))
            session.add(
                Transaction(
                    id="tx-water-auto",
                    account_id="bank-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("-300"),
                    # Description matches the fixed-cost description so
                    # _find_matching_transaction picks it up without a
                    # persisted FixedCostTransactionMatch.
                    description="Conta de agua",
                    category="Utilities",
                )
            )
            session.commit()

        # Sanity: the breakdown auto-matched it.
        breakdown = self.client.get(
            "/fixed-costs/by-month", params={"year_month": "2026-07"}
        ).json()
        entry = next(e for e in breakdown["entries"] if e["fixed_cost_id"] == cost["id"])
        self.assertEqual(entry["status"], "paid")
        self.assertEqual(entry["match_source"], "auto")
        self.assertEqual(entry["actual_amount"], 300.0)

        capacity = self._capacity("2026-07")
        # Fixed cost side: actual R$ 300, reserved R$ 300, no variance.
        self.assertEqual(capacity["fixed_cost_actual_total"], 300.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 300.0)
        self.assertEqual(capacity["fixed_cost_variance_total"], 0.0)
        # The auto-matched PIX must be invisible to the variable budget,
        # even though the pluggy category "Utilities" maps to a budgeted
        # category. Otherwise it gets counted twice.
        self.assertEqual(capacity["variable_budget_spent"], 0.0)
        self.assertEqual(capacity["variable_budget_consumed"], 0.0)
        self.assertEqual(capacity["unbudgeted_variable_spent"], 0.0)
        # Future month: max(target=1000, consumed=0) = 1000; 20300 - 300 (fixed) - 1000 (var target) = 19000
        self.assertEqual(capacity["budget_available_to_spend"], 19000.0)

    def test_auto_matched_card_fixed_cost_excluded_from_discretionary_invoice(self):
        """A card purchase auto-matched to a fixed cost should leave the
        discretionary invoice (the variable-budget concept), staying only in
        the gross invoice (the real cash obligation)."""
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-vyvanse-auto",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("740.00"),
                    description="Farmacia Vyvanse",
                    category="Pharmacy",
                )
            )
            session.commit()

        cost_category = self.client.post(
            "/fixed-cost-categories", json={"name": "Medicamento"}
        ).json()
        # Same description and amount → auto-match (no manual /matches POST)
        self.client.post(
            "/fixed-costs",
            json={
                "category_id": cost_category["id"],
                "description": "Vyvanse",
                "amount": 740,
                "due_day": 5,
            },
        )

        capacity = self._capacity()
        self.assertEqual(capacity["card_invoice_gross_total"], 740.0)
        self.assertEqual(capacity["card_invoice_discretionary_total"], 0.0)
        self.assertEqual(capacity["card_invoice_fixed_cost_total"], 740.0)
        self.assertEqual(capacity["fixed_cost_actual_total"], 740.0)

    # ----- 10. Monthly endpoint exposes new headline -----

    def test_monthly_endpoint_returns_budget_available_to_spend(self):
        """/spending-capacity/monthly must include the new headline field per
        month AND in the aggregate summary, alongside the legacy aliases."""
        self._make_water_fixed_cost(amount=300)
        response = self.client.get(
            "/spending-capacity/monthly", params={"months": 1}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        row = payload["months"][0]
        self.assertIn("budget_available_to_spend", row)
        self.assertIn("projected_cash_available", row)
        self.assertIn("fixed_cost_reserved_total", row)
        self.assertIn("variable_budget_consumed", row)
        self.assertIn("budget_available_to_spend", payload["summary"])
        # Sanity: the new headline matches the legacy alias for backward compat
        self.assertEqual(
            row["budget_available_to_spend"], row["discretionary_available"]
        )


    # ----- 10. Unbudgeted spend does NOT reduce disponível -----

    def test_unbudgeted_variable_spent_excluded_from_budget_available(self):
        """Current-month: unbudgeted spend is informational only, not in formula.
        Overage from a budgeted category DOES reduce availability for current months.

        Uses today=2026-06-30 so that 2026-06 is the current month and the
        current-month formula branch (consumed + overage) is exercised.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(Category(id=90, name="Lazer", color="#a855f7", sort_order=1))
            session.add(CategoryRule(pluggy_category="Entertainment", category_id=90))
            session.add(Category(id=91, name="Mercado", color="#22c55e", sort_order=2))
            session.add(CategoryRule(pluggy_category="Food", category_id=91))
            session.add(Budget(category_id=91, monthly_target=Decimal("500")))
            session.add(
                Transaction(
                    id="tx-lazer-1",
                    account_id="bank-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("-400"),
                    description="Cinema",
                    category="Entertainment",
                )
            )
            session.add(
                Transaction(
                    id="tx-food-over",
                    account_id="bank-1",
                    date=date(2026, 6, 12),
                    amount=Decimal("-600"),
                    description="Supermercado",
                    category="Food",
                )
            )
            session.commit()

        self._make_water_fixed_cost(amount=300)

        # Pin today=2026-06-30 → 2026-06 is current month (current-month formula).
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        # Unbudgeted NOT subtracted.
        self.assertEqual(capacity["unbudgeted_variable_spent"], 400.0)
        # Overage (100) and fixed (300) reduce availability.
        self.assertEqual(capacity["variable_budget_overage"], 100.0)
        self.assertEqual(capacity["fixed_cost_reserved_total"], 300.0)
        # 20300 - 300 (fixed) - 500 (consumed) - 100 (overage) = 19400
        self.assertEqual(capacity["budget_available_to_spend"], 19400.0)

    # ----- 12. card_invoice_remaining_to_include (current month) -----

    def test_card_invoice_gap_reduces_budget_available_current_month(self):
        """Current-month open invoice is based on PENDING transactions, NOT CreditCardBill.

        A CreditCardBill with due_date in the current month represents a *closed*
        prior billing cycle and must NOT be used as the open invoice source.
        With PENDING-based estimation: when PENDING transactions exceed gross
        tracked transactions, the gap reduces budget_available_to_spend; but since
        PENDING are a subset of gross, the gap is typically 0.

        This test verifies:
        - CreditCardBill is NOT the invoice source for the current month.
        - A PENDING transaction in the billing cycle sets the official total.
        - card_invoice_remaining_to_include = max(PENDING_total - gross_total, 0).
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(Category(id=95, name="Compras", color="#6366f1", sort_order=1))
            session.add(CategoryRule(pluggy_category="Shopping", category_id=95))
            # Set up close_date so the cycle is 2026-05-05 → 2026-06-04
            acct = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(
                    __import__("app.models", fromlist=["Account"]).Account
                ).where(
                    __import__("app.models", fromlist=["Account"]).Account.id == "credit-1"
                )
            ).one()
            from datetime import date as _date
            acct.credit_balance_close_date = _date(2026, 6, 4)
            session.add(acct)
            # PENDING transaction inside cycle — will be the official open total
            session.add(
                Transaction(
                    id="tx-card-pending-1",
                    account_id="credit-1",
                    date=date(2026, 6, 1),
                    amount=Decimal("800"),
                    description="Compra pendente",
                    category="Shopping",
                    status="PENDING",
                    bill_id=None,
                )
            )
            # Non-PENDING transaction also in gross (posted purchase)
            session.add(
                Transaction(
                    id="tx-card-posted-1",
                    account_id="credit-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("1000"),
                    description="Compra postada",
                    category="Shopping",
                )
            )
            # CreditCardBill — must NOT be used as open invoice source
            session.add(
                CreditCardBill(
                    id="bill-gap-1",
                    account_id="credit-1",
                    due_date=date(2026, 6, 15),
                    total_amount=Decimal("5000"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        # CreditCardBill NOT used — source is PENDING-based
        self.assertNotEqual(capacity["card_invoice_source"], "official_bill")
        self.assertEqual(capacity["card_invoice_source"], "open_invoice")
        # official_total = PENDING in cycle (800)
        self.assertEqual(capacity["card_invoice_official_total"], 800.0)
        self.assertEqual(capacity["card_invoice_current_open_total"], 800.0)
        # gross includes both PENDING (800) and posted (1000) = 1800
        self.assertGreaterEqual(capacity["card_invoice_gross_total"], 800.0)
        # gap = max(800 - 1800, 0) = 0 (PENDING ⊆ gross)
        self.assertEqual(capacity["card_invoice_remaining_to_include"], 0.0)
        # future_card_obligation_total is 0 for current month
        self.assertEqual(capacity["future_card_obligation_total"], 0.0)
        # New fields exposed
        self.assertIsNotNone(capacity["card_invoice_cycle_start"])
        self.assertIsNotNone(capacity["card_invoice_cycle_end"])
        self.assertEqual(capacity["card_invoice_transaction_count"], 1)
        # 20300 - 0 (fixed) - 0 (variable) - 0 (gap) = 20300
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    def test_card_invoice_no_gap_when_official_not_larger_current_month(self):
        """Current-month: when no PENDING transactions, open invoice total is 0
        and card_invoice_remaining_to_include is 0 regardless of any CreditCardBill.

        CreditCardBill is now ignored for current-month open invoice calculation.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            # Posted (non-PENDING) transaction — counted in gross but not open invoice
            session.add(
                Transaction(
                    id="tx-card-nogap-1",
                    account_id="credit-1",
                    date=date(2026, 6, 10),
                    amount=Decimal("2000"),
                    description="Compra cartao",
                    category="Shopping",
                )
            )
            # CreditCardBill must NOT be used as open invoice
            session.add(
                CreditCardBill(
                    id="bill-nogap-1",
                    account_id="credit-1",
                    due_date=date(2026, 6, 15),
                    total_amount=Decimal("1500"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        self.assertEqual(capacity["card_invoice_gross_total"], 2000.0)
        # Null-status tx (bill_id=null) IS counted by new rule → official = 2000
        self.assertNotEqual(capacity["card_invoice_source"], "official_bill")
        self.assertEqual(capacity["card_invoice_source"], "open_invoice")
        self.assertEqual(capacity["card_invoice_official_total"], 2000.0)
        # gap = max(2000 - 2000, 0) = 0 (tx already in gross)
        self.assertEqual(capacity["card_invoice_remaining_to_include"], 0.0)
        # 20300 - 0 - 0 - 0 = 20300
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    # ----- 13. planning_mode field -----

    def test_planning_mode_field_values(self):
        """planning_mode is 'current_month', 'future_month', or 'past_month'."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            c_cur = spending_capacity_summary(session, "2026-06", today=date(2026, 6, 15))
            c_fut = spending_capacity_summary(session, "2026-07", today=date(2026, 6, 15))
            c_pas = spending_capacity_summary(session, "2026-05", today=date(2026, 6, 15))

        self.assertEqual(c_cur["planning_mode"], "current_month")
        self.assertEqual(c_fut["planning_mode"], "future_month")
        self.assertEqual(c_pas["planning_mode"], "past_month")
        # is_future_month must be consistent with planning_mode
        self.assertFalse(c_cur["is_future_month"])
        self.assertTrue(c_fut["is_future_month"])
        self.assertFalse(c_pas["is_future_month"])

    # ----- 14. Future-month projected formula -----

    def test_future_month_uses_variable_budget_total_not_consumed(self):
        """Future month: formula uses variable_budget_total (full target), not
        variable_budget_consumed, even when future installments exist in the DB.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(Category(id=80, name="Lazer", color="#a855f7", sort_order=1))
            session.add(CategoryRule(pluggy_category="Entertainment", category_id=80))
            session.add(Budget(category_id=80, monthly_target=Decimal("500")))
            # Future installment already in DB — only partially uses the R$500 envelope.
            session.add(
                Transaction(
                    id="tx-future-installment",
                    account_id="credit-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("200"),
                    description="Parcela curso",
                    category="Entertainment",
                )
            )
            session.commit()

        self._make_water_fixed_cost(amount=300)

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        # variable_budget_consumed reflects the installment (200).
        self.assertEqual(capacity["variable_budget_consumed"], 200.0)
        # variable_budget_reserved equals the full target for future months.
        self.assertEqual(capacity["variable_budget_reserved"], 500.0)
        # The installment (200) is also picked up as scheduled_installments fallback.
        # Formula: 20300 - 300 (fixed_planned) - 500 (variable_budget_total)
        #          - 200 (scheduled installment) = 19300
        self.assertEqual(capacity["budget_available_to_spend"], 19300.0)

    def test_future_month_no_account_balance_used(self):
        """Future month: Account.balance is never used as the card obligation."""
        from app.services.spending_capacity import spending_capacity_summary
        from sqlmodel import select

        with Session(self.engine) as session:
            # Give the credit account a large balance (current open invoice snapshot).
            acct = session.exec(select(Account).where(Account.id == "credit-1")).one()
            acct.balance = Decimal("8000")
            session.add(acct)
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        # No official bill for 2026-07 → future_card_obligation_total must be 0.
        self.assertEqual(capacity["future_card_obligation_total"], 0.0)
        # Account.balance (8000) must NOT appear as the card obligation.
        self.assertEqual(capacity["card_invoice_source"], "none")
        # Full income available (no fixed costs, no budgets, no reserve).
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    def test_future_month_official_bill_is_full_obligation(self):
        """Future month: when a CreditCardBill with due_date in the future month
        exists, future_card_obligation_total equals the full bill total (not just
        the gap), and it is subtracted from budget_available_to_spend.

        The bill covers a prior billing cycle — those purchases are NOT in the
        future month's variable budget, so there is no double-counting.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            # Official bill due in July 2026 (prior billing cycle).
            session.add(
                CreditCardBill(
                    id="bill-future-1",
                    account_id="credit-1",
                    due_date=date(2026, 7, 10),
                    total_amount=Decimal("3000"),
                )
            )
            # A July installment in a budget category — separate from the bill above.
            session.add(Category(id=85, name="Lazer", color="#a855f7", sort_order=1))
            session.add(Budget(category_id=85, monthly_target=Decimal("600")))
            session.add(
                Transaction(
                    id="tx-july-parcela",
                    account_id="credit-1",
                    date=date(2026, 7, 15),
                    amount=Decimal("200"),
                    description="Parcela notebook",
                    category="Electronics",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        self.assertEqual(capacity["card_invoice_source"], "official_bill")
        # future_card_obligation_total = full bill (not gap).
        self.assertEqual(capacity["future_card_obligation_total"], 3000.0)
        # card_invoice_remaining_to_include is still computed for info but not
        # in the future-month formula.
        self.assertGreaterEqual(capacity["card_invoice_remaining_to_include"], 0.0)
        # Formula: 20300 - 0 (fixed) - 600 (variable_budget_total) - 3000 (bill) - 0 (reserve)
        self.assertEqual(capacity["budget_available_to_spend"], 16700.0)

    def test_future_month_no_card_bill_uses_scheduled_installments(self):
        """Future month without an official bill: future credit-card transactions are
        picked up by scheduled_installments_for_month and subtracted as
        future_card_obligation_total (source = 'scheduled_installments').
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            # Category with NO budget → any spend lands in unbudgeted.
            session.add(Category(id=77, name="Eletronicos", color="#6366f1", sort_order=1))
            session.add(CategoryRule(pluggy_category="Electronics", category_id=77))
            # Future installment — no official bill for July.
            session.add(
                Transaction(
                    id="tx-installment-no-budget",
                    account_id="credit-1",
                    date=date(2026, 7, 20),
                    amount=Decimal("400"),
                    description="Parcela TV",
                    category="Electronics",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        # Installment picked up as scheduled_installments fallback.
        self.assertEqual(capacity["future_card_obligation_source"], "scheduled_installments")
        self.assertEqual(capacity["future_card_obligation_count"], 1)
        self.assertEqual(capacity["future_card_obligation_total"], 400.0)
        # Subtracted from budget_available_to_spend.
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0 - 400.0)

    def test_future_month_scheduled_installments_multiple_transactions(self):
        """Future month: multiple future card transactions sum into
        future_card_obligation_total when there is no official bill.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-parcela-1",
                    account_id="credit-1",
                    date=date(2026, 7, 5),
                    amount=Decimal("1000"),
                    description="Parcela A",
                    category="Shopping",
                )
            )
            session.add(
                Transaction(
                    id="tx-parcela-2",
                    account_id="credit-1",
                    date=date(2026, 7, 15),
                    amount=Decimal("500"),
                    description="Parcela B",
                    category="Shopping",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["future_card_obligation_source"], "scheduled_installments")
        self.assertEqual(capacity["future_card_obligation_count"], 2)
        self.assertEqual(capacity["future_card_obligation_total"], 1500.0)
        # 20300 - 1500 = 18800
        self.assertEqual(capacity["budget_available_to_spend"], 18800.0)

    def test_scheduled_installments_excludes_negative_amounts(self):
        """Negative-amount transactions (refunds, cancellations) must NOT be
        counted as future obligations. Only tx.amount > 0 enters the total.

        Mirrors the real-world "CANC PARCELA SEM J" entries returned by
        Pluggy with negative amounts that were previously inflating the total
        via abs(amount).
        """
        from app.services.spending_capacity import spending_capacity_summary
        from app.services.credit_card_invoice import scheduled_installments_for_month

        with Session(self.engine) as session:
            # Normal purchase — must be counted (amount > 0)
            session.add(
                Transaction(
                    id="tx-future-pos",
                    account_id="credit-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("800"),
                    description="Parcela TV 03/12",
                    category="Electronics",
                )
            )
            # Cancellation / refund — must NOT be counted (amount < 0)
            session.add(
                Transaction(
                    id="tx-future-canc",
                    account_id="credit-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("-200"),
                    description="CANC PARCELA SEM J03/12",
                    category="Electronics",
                )
            )
            # Zero-amount — must NOT be counted
            session.add(
                Transaction(
                    id="tx-future-zero",
                    account_id="credit-1",
                    date=date(2026, 7, 10),
                    amount=Decimal("0"),
                    description="Ajuste zero",
                    category="Electronics",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            installments = scheduled_installments_for_month(
                session, "2026-07", today=date(2026, 6, 15)
            )

        # Only the positive tx (800) is counted
        self.assertEqual(installments["count"], 1)
        self.assertEqual(installments["total"], 800.0)
        self.assertEqual(installments["transactions"][0]["transaction_id"], "tx-future-pos")

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["future_card_obligation_source"], "scheduled_installments")
        self.assertEqual(capacity["future_card_obligation_total"], 800.0)
        # 20300 - 800 = 19500 (cancellation not subtracted)
        self.assertEqual(capacity["budget_available_to_spend"], 19500.0)

    def test_future_month_bill_takes_priority_over_installments(self):
        """Future month: official bill overrides scheduled_installments."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(
                CreditCardBill(
                    id="bill-priority-1",
                    account_id="credit-1",
                    due_date=date(2026, 7, 10),
                    total_amount=Decimal("3000"),
                )
            )
            # Future installment that should NOT add to obligation (bill wins).
            session.add(
                Transaction(
                    id="tx-installment-with-bill",
                    account_id="credit-1",
                    date=date(2026, 7, 20),
                    amount=Decimal("400"),
                    description="Parcela notebook",
                    category="Shopping",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["future_card_obligation_source"], "official_bill")
        self.assertEqual(capacity["future_card_obligation_total"], 3000.0)
        # Installment (400) does NOT add on top of the bill.
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0 - 3000.0)

    def test_future_month_no_installments_source_none(self):
        """Future month with no bill, no account_balance_due_month, no future
        transactions: source = 'none', obligation = 0.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        self.assertEqual(capacity["future_card_obligation_source"], "none")
        self.assertEqual(capacity["future_card_obligation_total"], 0.0)
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    def test_future_month_account_balance_with_due_date_in_month(self):
        """Future month: Account.balance is used when credit_balance_due_date falls
        in that exact future month. source = 'account_balance_due_month' and
        future_card_obligation_total equals the account balance.
        """
        from app.services.spending_capacity import spending_capacity_summary
        from sqlmodel import select

        with Session(self.engine) as session:
            acct = session.exec(select(Account).where(Account.id == "credit-1")).one()
            acct.balance = Decimal("40132.57")
            acct.credit_balance_due_date = date(2026, 7, 10)
            session.add(acct)
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        self.assertEqual(capacity["card_invoice_source"], "account_balance_due_month")
        self.assertAlmostEqual(capacity["future_card_obligation_total"], 40132.57, places=2)
        # Formula: 20300 - 40132.57 = -19832.57
        self.assertAlmostEqual(capacity["budget_available_to_spend"], 20300.0 - 40132.57, places=2)

    def test_future_month_account_balance_due_date_in_other_month(self):
        """Future month: Account.balance is NOT used when credit_balance_due_date
        falls in a different month. future_card_obligation_total must be 0.
        """
        from app.services.spending_capacity import spending_capacity_summary
        from sqlmodel import select

        with Session(self.engine) as session:
            acct = session.exec(select(Account).where(Account.id == "credit-1")).one()
            acct.balance = Decimal("40132.57")
            # Due date is in August, not July
            acct.credit_balance_due_date = date(2026, 8, 10)
            session.add(acct)
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 15)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        # credit_balance_due_date is in 2026-08, not 2026-07 → not used
        self.assertNotEqual(capacity["card_invoice_source"], "account_balance_due_month")
        self.assertEqual(capacity["future_card_obligation_total"], 0.0)
        self.assertEqual(capacity["budget_available_to_spend"], 20300.0)

    def test_current_month_not_broken_by_future_month_changes(self):
        """Regression: current-month formula (consumed + overage, gap-based card)
        must be unchanged after adding the future-month branch.
        """
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(Category(id=70, name="Mercado", color="#22c55e", sort_order=1))
            session.add(CategoryRule(pluggy_category="Food", category_id=70))
            session.add(Budget(category_id=70, monthly_target=Decimal("800")))
            # Card purchase within the budget.
            session.add(
                Transaction(
                    id="tx-cur-card",
                    account_id="credit-1",
                    date=date(2026, 6, 8),
                    amount=Decimal("600"),
                    description="Compra mercado",
                    category="Food",
                )
            )
            # Official bill larger than the transaction → gap = 200.
            session.add(
                CreditCardBill(
                    id="bill-cur-1",
                    account_id="credit-1",
                    due_date=date(2026, 6, 10),
                    total_amount=Decimal("800"),
                )
            )
            session.commit()

        self._make_water_fixed_cost(amount=200)

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        # CreditCardBill NOT used for current-month open invoice.
        # No PENDING transactions → gap = 0.
        self.assertEqual(capacity["card_invoice_remaining_to_include"], 0.0)
        # future_card_obligation_total is 0 for current month.
        self.assertEqual(capacity["future_card_obligation_total"], 0.0)
        # variable_budget_reserved = consumed (600), not target (800).
        self.assertEqual(capacity["variable_budget_consumed"], 600.0)
        self.assertEqual(capacity["variable_budget_reserved"], 600.0)
        # 20300 - 200 (fixed) - 600 (var consumed) - 0 (card gap) = 19500
        self.assertEqual(capacity["budget_available_to_spend"], 19500.0)


class CurrentOpenCardInvoiceTest(unittest.TestCase):
    """Open-invoice logic, now owned by planning_invoice_for_month() and
    surfaced through spending_capacity_summary().
    """

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

        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-1",
                    name="Credit",
                    type="CREDIT",
                    credit_balance_close_date=date(2026, 6, 4),
                )
            )
            session.add(
                ExpectedIncome(
                    description="Salario",
                    amount=Decimal("10000"),
                    expected_day=5,
                )
            )
            session.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    # ── 1. bill_id-null in cycle are counted ──────────────────────────────────

    def test_bill_id_null_in_cycle_sets_open_invoice(self):
        """All transactions with bill_id null within the billing cycle are counted,
        regardless of status. Both PENDING and null-status (already-settled)
        purchases must be included.
        """
        from app.services.credit_card_invoice import planning_invoice_for_month

        # Cycle for close_date=2026-06-04 is 2026-05-05 to 2026-06-04
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-pending-in",
                    account_id="credit-1",
                    date=date(2026, 5, 20),
                    amount=Decimal("300"),
                    description="Recent purchase (PENDING)",
                    status="PENDING",
                    bill_id=None,
                )
            )
            session.add(
                Transaction(
                    id="tx-settled-in",
                    account_id="credit-1",
                    date=date(2026, 5, 20),
                    amount=Decimal("500"),
                    description="Settled purchase (no status)",
                    status=None,
                    bill_id=None,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(result["source"], "open_invoice")
        # Both PENDING and null-status are counted → 300 + 500 = 800
        self.assertEqual(result["amount"], 800.0)
        self.assertEqual(result["transaction_count"], 2)
        self.assertEqual(result["cycle_start"], "2026-05-05")
        self.assertEqual(result["cycle_end"], "2026-06-04")

    # ── 2. Transactions outside cycle are excluded ────────────────────────────

    def test_pending_outside_cycle_excluded(self):
        """Transactions outside the billing cycle must not be counted."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            # Inside cycle (2026-05-05 to 2026-06-04) → counted
            session.add(
                Transaction(
                    id="tx-inside",
                    account_id="credit-1",
                    date=date(2026, 6, 4),
                    amount=Decimal("100"),
                    description="Last day of cycle",
                    status="PENDING",
                    bill_id=None,
                )
            )
            # OUTSIDE cycle (one day after cycle end) → excluded
            session.add(
                Transaction(
                    id="tx-outside",
                    account_id="credit-1",
                    date=date(2026, 6, 5),
                    amount=Decimal("999"),
                    description="Next cycle",
                    status="PENDING",
                    bill_id=None,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(result["source"], "open_invoice")
        self.assertEqual(result["amount"], 100.0)

    # ── 3. Null-status counted; bill_id-filled excluded from open invoice ─────

    def test_null_status_with_no_bill_id_counted_in_open_invoice(self):
        """Transactions with status=null (already-settled) and bill_id=null
        must be counted in the open invoice; bill_id-filled ones must not."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            # Null-status, in cycle, no bill_id → MUST be counted
            session.add(
                Transaction(
                    id="tx-settled-null",
                    account_id="credit-1",
                    date=date(2026, 5, 20),
                    amount=Decimal("500"),
                    description="Settled purchase",
                    status=None,
                    bill_id=None,
                )
            )
            # Null-status, in cycle, bill_id filled → MUST be excluded from open invoice
            session.add(
                Transaction(
                    id="tx-closed-bill",
                    account_id="credit-1",
                    date=date(2026, 5, 20),
                    amount=Decimal("999"),
                    description="Already on a closed bill",
                    status=None,
                    bill_id="some-bill-id",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        # Only the bill_id=null tx is in the open-invoice estimate
        self.assertEqual(result["source"], "open_invoice")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["transaction_count"], 1)

    # ── 4. bill_id-filled tx is not part of the open-invoice tier ─────────────

    def test_bill_id_filled_not_in_open_invoice(self):
        """A transaction that already has a bill_id must not produce an
        open_invoice source — the cycle/month tiers exclude it."""
        from app.services.credit_card_invoice import planning_invoice_for_month

        with Session(self.engine) as session:
            session.add(
                Transaction(
                    id="tx-with-bill",
                    account_id="credit-1",
                    date=date(2026, 5, 20),
                    amount=Decimal("400"),
                    description="Already in a bill",
                    status="PENDING",
                    bill_id="some-bill-id",
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        # The bill_id-filled tx is excluded from the open-invoice tier.
        self.assertNotEqual(result["source"], "open_invoice")

    # ── 5. CreditCardBill not used for current month open invoice ─────────────

    def test_creditcardbill_not_used_for_current_month_open_invoice(self):
        """CreditCardBill with due_date in the current month must NOT influence
        the open invoice estimate via spending_capacity_summary."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(
                CreditCardBill(
                    id="bill-current",
                    account_id="credit-1",
                    due_date=date(2026, 6, 10),
                    total_amount=Decimal("9999"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "current_month")
        self.assertNotEqual(capacity["card_invoice_source"], "official_bill")
        # Official total must NOT be the bill amount
        self.assertNotEqual(capacity["card_invoice_official_total"], 9999.0)

    # ── 6. No close_date → fallback to month transactions ────────────────────

    def test_no_close_date_fallback_to_month_transactions(self):
        """When no account has credit_balance_close_date, fall back to bill_id-null
        transactions within the current calendar month."""
        from app.services.credit_card_invoice import planning_invoice_for_month
        from sqlmodel import select

        with Session(self.engine) as session:
            acct = session.exec(select(Account).where(Account.id == "credit-1")).one()
            acct.credit_balance_close_date = None
            session.add(acct)
            session.add(
                Transaction(
                    id="tx-month-pending",
                    account_id="credit-1",
                    date=date(2026, 6, 15),
                    amount=Decimal("250"),
                    description="Month pending",
                    status="PENDING",
                    bill_id=None,
                )
            )
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(result["source"], "open_invoice")
        self.assertEqual(result["amount"], 250.0)

    # ── 7. No open-invoice txs → Account.balance fallback ────────────────────

    def test_no_pending_falls_back_to_account_balance(self):
        """When no bill_id-null transactions exist, the open invoice falls back
        to Account.balance. source = 'account_balance'."""
        from app.services.credit_card_invoice import planning_invoice_for_month
        from app.services.spending_capacity import spending_capacity_summary
        from sqlmodel import select

        with Session(self.engine) as session:
            acct = session.exec(select(Account).where(Account.id == "credit-1")).one()
            acct.balance = Decimal("2500")
            acct.credit_balance_due_date = date(2026, 6, 10)
            session.add(acct)
            session.commit()

        with Session(self.engine) as session:
            result = planning_invoice_for_month(
                session, "2026-06", today=date(2026, 6, 30)
            )

        self.assertEqual(result["source"], "account_balance")
        self.assertEqual(result["amount"], 2500.0)
        self.assertEqual(result["transaction_count"], 0)

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-06", today=date(2026, 6, 30)
            )
        self.assertEqual(capacity["card_invoice_source"], "account_balance")
        self.assertEqual(capacity["card_invoice_official_total"], 2500.0)

    # ── 8. Future month uses official bill ───────────────────────────────────

    def test_future_month_not_affected_by_current_month_changes(self):
        """Future months use the official CreditCardBill / scheduled installments
        logic. The open-invoice estimate only applies to current_month mode."""
        from app.services.spending_capacity import spending_capacity_summary

        with Session(self.engine) as session:
            session.add(
                CreditCardBill(
                    id="bill-future",
                    account_id="credit-1",
                    due_date=date(2026, 7, 10),
                    total_amount=Decimal("3000"),
                )
            )
            session.commit()

        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-07", today=date(2026, 6, 30)
            )

        self.assertEqual(capacity["planning_mode"], "future_month")
        # Future month: CreditCardBill with due_date in that month IS still used
        self.assertEqual(capacity["card_invoice_source"], "official_bill")
        self.assertEqual(capacity["future_card_obligation_total"], 3000.0)
        # Current-open fields are not populated for future month
        self.assertEqual(capacity["card_invoice_current_open_total"], 0.0)
        self.assertEqual(capacity["card_invoice_current_open_source"], "none")


if __name__ == "__main__":
    unittest.main()
