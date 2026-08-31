"""The simplified UI must not receive retired presentation-only summaries."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, CreditCardBill, Item, Transaction
from app.security import SecuritySettings
from app.services.year_month import shift_year_month


CARD_FIELDS = {
    "account_id",
    "account_name",
    "institution_name",
    "card_brand",
    "card_last_four",
    "total_amount",
}


@pytest.fixture(params=[None, "Visa", "CAIXA ICONE VISA"], ids=["empty", "card", "caixa"])
def ui_client(request):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    today = date.today()
    year_month = today.strftime("%Y-%m")
    if request.param:
        with Session(engine) as session:
            session.add(
                Item(
                    id="item-ui",
                    connector_id="test",
                    connector_name="Test",
                    status="UPDATED",
                    is_active=True,
                )
            )
            session.add(
                Account(
                    id="card-ui",
                    item_id="item-ui",
                    name=request.param,
                    type="CREDIT",
                    number="1234",
                    is_active=True,
                )
            )
            session.add(
                Transaction(
                    id="purchase-ui",
                    account_id="card-ui",
                    date=today,
                    amount=Decimal("125"),
                    description="Compra",
                    category="Shopping",
                    status="PENDING",
                    bill_forecast_month=year_month,
                )
            )
            session.add(
                CreditCardBill(
                    id="future-bill-ui",
                    account_id="card-ui",
                    due_date=date.fromisoformat(f"{shift_year_month(year_month, 2)}-08"),
                    total_amount=Decimal("80"),
                )
            )
            session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override_session
    settings = SecuritySettings(_env_file=None, openfinance_require_auth=False)
    try:
        with patch("app.security.get_security_settings", return_value=settings):
            client = TestClient(app)
            try:
                yield client
            finally:
                client.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def test_upcoming_only_returns_active_ui_fields(ui_client):
    response = ui_client.get("/upcoming")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"months"}
    assert payload["months"]
    for month in payload["months"]:
        assert set(month) == {
            "month",
            "total",
            "count",
            "is_current_invoice",
            "cards",
            "categories",
            "transactions",
        }
        for card in month["cards"]:
            assert set(card) == CARD_FIELDS
        for category in month["categories"]:
            assert "source" not in category


def test_current_invoice_keeps_financial_details_without_old_indicators(ui_client):
    response = ui_client.get("/credit-card/current-invoice")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "amount",
        "source",
        "account_count",
        "invoice_month",
        "cutoff_date",
        "cards",
        "categories",
        "transaction_count",
        "raw_purchase_transactions",
        "recent_purchase_transactions",
    }
    assert payload["amount"] == sum(card["total_amount"] for card in payload["cards"])
    assert payload["transaction_count"] == len(payload["raw_purchase_transactions"])
    for card in payload["cards"]:
        assert set(card) == CARD_FIELDS | {"transaction_count"}


def test_history_does_not_restore_source_badges_or_difference_text(ui_client):
    response = ui_client.get("/credit-card-invoices/monthly?months=2")
    assert response.status_code == 200
    for month in response.json()["months"]:
        assert {"total", "cards", "categories", "transactions"} <= month.keys()
        assert (
            not {
                "invoice_total_source",
                "card_breakdown_source",
                "dashboard_current_invoice_source",
                "classified_purchase_difference_from_invoice",
            }
            & month.keys()
        )
        for card in month["cards"]:
            assert "source" not in card
        for category in month["categories"]:
            assert "source" not in category


@pytest.mark.parametrize("offset", [-1, 0, 1, 2])
def test_planning_preserves_capacity_without_retired_visual_summaries(ui_client, offset):
    year_month = shift_year_month(date.today().strftime("%Y-%m"), offset)
    response = ui_client.get(f"/planning/month/{year_month}")
    assert response.status_code == 200
    payload = response.json()
    capacity = payload["capacity"]
    assert {
        "budget_available_to_spend",
        "days_remaining_in_month",
        "plan_status",
    } <= capacity.keys()
    assert (
        not {
            "card_invoice_current_open_label",
            "income_received_progress_pct",
            "future_card_obligation_display_month",
            "planned_expense_total",
            "planned_after_fixed_costs",
            "remaining_after_plan",
            "remaining_after_invoice",
            "remaining_after_plan_and_invoice",
        }
        & capacity.keys()
    )
    assert "source_label" not in payload["credit_card_invoice"]
    invoice_response = ui_client.get(f"/credit-card/invoice/{year_month}")
    assert invoice_response.status_code == 200
    assert "source_label" not in invoice_response.json()
