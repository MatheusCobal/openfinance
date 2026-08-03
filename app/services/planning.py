from datetime import date
from typing import Any, Dict, Optional

from sqlmodel import Session

from app.services.credit_card_invoice import scheduled_installments_for_month
from app.services.fixed_costs import (
    FixedCostValidationError,
    _shift_year_month,
    monthly_breakdown,
)
from app.services.spending_capacity import spending_capacity_summary

_CAPACITY_DETAIL_KEYS = {
    "expected_income",
    "fixed_costs",
    "planning_invoice",
    "variable_budgets",
}


def upcoming_months(
    session: Session,
    start_year_month: str,
    months: int,
    today: Optional[date] = None,
    user_id: Optional[int] = None,
) -> list[Dict[str, Any]]:
    if not (1 <= months <= 24):
        raise FixedCostValidationError("months must be between 1 and 24")
    today = today if today is not None else date.today()
    out: list[Dict[str, Any]] = []
    for offset in range(months):
        ym = _shift_year_month(start_year_month, offset)
        breakdown = monthly_breakdown(session, ym, today=today, user_id=user_id)
        installments = scheduled_installments_for_month(session, ym, today=today, user_id=user_id)
        breakdown["installments"] = installments
        breakdown["projected_total"] = breakdown["total"] + installments["total"]
        out.append(breakdown)
    return out


def planning_month_summary(
    session: Session,
    year_month: str,
    today: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = today if today is not None else date.today()
    capacity = spending_capacity_summary(session, year_month, today=today, user_id=user_id)
    income = capacity["expected_income"]
    fixed_costs = capacity["fixed_costs"]
    variable_budgets = capacity["variable_budgets"]
    planning_invoice = capacity["planning_invoice"]

    budget_summary = variable_budgets["summary"]
    return {
        "year_month": year_month,
        "income": {
            "expected": income["total"],
            "received": capacity["received_income_total"],
            "to_receive": capacity["income_to_receive"],
            "entries": income["entries"],
        },
        "fixed_costs": {
            "planned": fixed_costs["planned_total"],
            "actual": fixed_costs["actual_total"],
            "pending": fixed_costs["pending_total"],
            "reserved_or_actual": fixed_costs["reserved_or_actual_total"],
            "entries": fixed_costs["entries"],
        },
        "variable_budgets": {
            "planned": budget_summary["target"],
            "consumed": budget_summary["target_consumed"],
            "remaining": budget_summary["target_remaining"],
            "overage": budget_summary["target_overage"],
            "items": variable_budgets["items"],
        },
        "credit_card_invoice": planning_invoice,
        "capacity": {
            key: value for key, value in capacity.items() if key not in _CAPACITY_DETAIL_KEYS
        },
    }
