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
        self.assertEqual(capacity["savings_target_total"], 0.0)
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

        before = self.client.get(
            "/budgets/progress", params={"year_month": "2026-05"}
        ).json()
        before_items = {
            item["category_name"]: item for item in before["items"]
        }
        self.assertEqual(before_items["Saúde"]["projected_spent"], 740.0)

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


class SavingsTargetTest(unittest.TestCase):
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

    def test_default_target_crud(self):
        # Empty by default
        self.assertEqual(
            self.client.get("/savings-target").json(),
            {"monthly_target": 0.0},
        )

        # Set + read
        self.client.put("/savings-target", json={"monthly_target": 1500})
        self.assertEqual(
            self.client.get("/savings-target").json(),
            {"monthly_target": 1500.0},
        )

        # Update + read
        self.client.put("/savings-target", json={"monthly_target": 2200})
        self.assertEqual(
            self.client.get("/savings-target").json(),
            {"monthly_target": 2200.0},
        )

        # Clear
        self.assertEqual(self.client.delete("/savings-target").status_code, 204)
        self.assertEqual(
            self.client.get("/savings-target").json(),
            {"monthly_target": 0.0},
        )

    def test_monthly_override_wins_and_returns_breakdown(self):
        self.client.put("/savings-target", json={"monthly_target": 1000})
        month = self.client.get("/savings-target/months/2026-05").json()
        self.assertEqual(month["default_target"], 1000.0)
        self.assertEqual(month["monthly_target"], 1000.0)
        self.assertEqual(month["scope"], "default")
        self.assertFalse(month["is_override"])

        self.client.put(
            "/savings-target/months/2026-05", json={"monthly_target": 1800}
        )
        month = self.client.get("/savings-target/months/2026-05").json()
        self.assertEqual(month["default_target"], 1000.0)
        self.assertEqual(month["monthly_target"], 1800.0)
        self.assertEqual(month["scope"], "month")
        self.assertTrue(month["is_override"])

        # Different month falls back to default
        other = self.client.get("/savings-target/months/2026-06").json()
        self.assertEqual(other["monthly_target"], 1000.0)
        self.assertFalse(other["is_override"])

        # Delete override → back to default
        self.assertEqual(
            self.client.delete("/savings-target/months/2026-05").status_code, 204
        )
        month = self.client.get("/savings-target/months/2026-05").json()
        self.assertEqual(month["monthly_target"], 1000.0)
        self.assertFalse(month["is_override"])

    def test_rejects_invalid_inputs(self):
        self.assertEqual(
            self.client.put(
                "/savings-target", json={"monthly_target": -5}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.put(
                "/savings-target/months/2026-13", json={"monthly_target": 100}
            ).status_code,
            400,
        )
        # Deleting a non-existent override returns 404
        self.assertEqual(
            self.client.delete(
                "/savings-target/months/2026-05"
            ).status_code,
            404,
        )

    def test_spending_capacity_subtracts_savings_target(self):
        # No savings target yet → discretionary == available
        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()
        baseline_available = capacity["available_to_spend"]
        self.assertEqual(capacity["savings_target_total"], 0.0)
        self.assertEqual(capacity["discretionary_available"], baseline_available)
        self.assertEqual(baseline_available, 10000.0)  # no fixed/variable yet

        # With a default target of 2000, discretionary drops by 2000
        self.client.put("/savings-target", json={"monthly_target": 2000})
        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()
        self.assertEqual(capacity["savings_target_total"], 2000.0)
        self.assertEqual(capacity["discretionary_available"], 8000.0)
        self.assertEqual(capacity["planned_expense_total"], 2000.0)
        self.assertEqual(capacity["savings_target"]["scope"], "default")

        # Override the month with a higher target
        self.client.put(
            "/savings-target/months/2026-05", json={"monthly_target": 3500}
        )
        capacity = self.client.get(
            "/spending-capacity", params={"year_month": "2026-05"}
        ).json()
        self.assertEqual(capacity["savings_target_total"], 3500.0)
        self.assertEqual(capacity["discretionary_available"], 6500.0)
        self.assertEqual(capacity["savings_target"]["scope"], "month")
        self.assertTrue(capacity["savings_target"]["is_override"])

        # A different month still uses the default (2000), proving overrides
        # are month-scoped.
        june = self.client.get(
            "/spending-capacity", params={"year_month": "2026-06"}
        ).json()
        self.assertEqual(june["savings_target_total"], 2000.0)

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
        from app.services.fixed_costs import spending_capacity_summary

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
        from app.services.fixed_costs import spending_capacity_summary

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
        # (you can't spend negative money per day).
        self.client.put("/savings-target", json={"monthly_target": 15000})
        from app.services.fixed_costs import spending_capacity_summary as cap

        with Session(self.engine) as session:
            capacity = cap(session, "2026-05", today=date(2026, 5, 11))
            self.assertLess(capacity["discretionary_available"], 0)
            self.assertEqual(capacity["daily_discretionary_remaining"], 0.0)

    def test_plan_status_flag_transitions(self):
        """#6 — healthy / tight / over based on the discretionary margin."""
        from app.services.fixed_costs import spending_capacity_summary

        # Healthy: no expenses, everything is discretionary
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "healthy")

        # Tight: savings target eats >90% of income (margin under 10%)
        self.client.put("/savings-target", json={"monthly_target": 9500})
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "tight")

        # Over: target exceeds income, discretionary goes negative
        self.client.put("/savings-target", json={"monthly_target": 12000})
        with Session(self.engine) as session:
            capacity = spending_capacity_summary(
                session, "2026-05", today=date(2026, 5, 11)
            )
            self.assertEqual(capacity["plan_status"], "over")

    def test_plan_status_unknown_when_no_income(self):
        """No expected income configured → can't grade the plan."""
        from app.services.fixed_costs import spending_capacity_summary
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

        from app.services.fixed_costs import upcoming_months

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

        from app.services.fixed_costs import scheduled_installments_summary

        with Session(self.engine) as session:
            # Today is AFTER the transaction → not a future installment
            summary = scheduled_installments_summary(
                session, "2026-05", today=date(2026, 5, 20)
            )
            self.assertEqual(summary["total"], 0.0)

            # Today is BEFORE the transaction → it counts
            summary = scheduled_installments_summary(
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
        from app.services.fixed_costs import spending_capacity_summary

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


if __name__ == "__main__":
    unittest.main()
