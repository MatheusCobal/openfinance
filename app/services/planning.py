from datetime import date
from typing import Any, Dict, Optional

from sqlmodel import Session

from app.services.budgets import budget_progress_summary
from app.services.credit_card_invoice import (
    planning_invoice_for_month,
    scheduled_installments_for_month,
)
from app.services.expected_income import monthly_breakdown as expected_income_breakdown
from app.services.fixed_costs import (
    FixedCostValidationError,
    _month_bounds,
    _shift_year_month,
    monthly_breakdown,
)
from app.services.spending_capacity import spending_capacity_summary


def upcoming_months(
    session: Session,
    start_year_month: str,
    months: int,
    today: Optional[date] = None,
) -> list[Dict[str, Any]]:
    if not (1 <= months <= 24):
        raise FixedCostValidationError("months must be between 1 and 24")
    today = today if today is not None else date.today()
    out: list[Dict[str, Any]] = []
    for offset in range(months):
        ym = _shift_year_month(start_year_month, offset)
        breakdown = monthly_breakdown(session, ym)
        installments = scheduled_installments_for_month(session, ym, today=today)
        breakdown["installments"] = installments
        breakdown["projected_total"] = breakdown["total"] + installments["total"]
        out.append(breakdown)
    return out


def planning_month_summary(
    session: Session,
    year_month: str,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    today = today if today is not None else date.today()
    first_day, last_day = _month_bounds(year_month)

    income = expected_income_breakdown(session, year_month)
    fixed_costs = monthly_breakdown(session, year_month)
    fixed_cost_accounted_ids = {
        entry["matched_transaction"]["id"]
        for entry in fixed_costs["entries"]
        if entry.get("matched_transaction") and entry["matched_transaction"].get("id")
    }
    variable_budgets = budget_progress_summary(
        session,
        year_month=year_month,
        first_day=first_day,
        last_day=last_day,
        today=today,
        fixed_cost_accounted_transaction_ids=fixed_cost_accounted_ids,
    )
    planning_invoice = planning_invoice_for_month(session, year_month, today=today)
    capacity = spending_capacity_summary(session, year_month, today=today)

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
            "available_to_spend": capacity["available_to_spend"],
            "daily_discretionary_remaining": capacity[
                "daily_discretionary_remaining"
            ],
            "days_remaining_in_month": capacity["days_remaining_in_month"],
            "plan_status": capacity["plan_status"],
        },
        "raw": {
            "spending_capacity": capacity,
        },
    }
