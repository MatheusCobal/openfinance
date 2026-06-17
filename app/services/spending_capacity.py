from datetime import date
from decimal import Decimal
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
from app.services.transaction_reports import invoice_summary
from app.services.transactions import (
    bank_income_transactions,
    bank_inflow_transactions,
    bank_outflow_transactions,
)


def spending_capacity_summary(
    session: Session,
    year_month: str,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    first_day, last_day = _month_bounds(year_month)
    today = today if today is not None else date.today()
    income = expected_income_breakdown(session, year_month)
    fixed = monthly_breakdown(session, year_month)
    # Transactions already accounted for as a fixed cost - manual matches
    # AND auto-detected matches that monthly_breakdown produced above - must
    # NOT also be counted in the discretionary invoice or in the variable
    # budget.
    fixed_cost_accounted_ids: set[str] = {
        entry["matched_transaction"]["id"]
        for entry in fixed["entries"]
        if entry.get("matched_transaction") and entry["matched_transaction"].get("id")
    }
    invoice = invoice_summary(
        session,
        from_date=first_day,
        to_date=last_day,
        exclude_transaction_ids=fixed_cost_accounted_ids,
    )

    # Resolve the planning invoice first so we can use the billing-cycle window
    # for variable budgets (fatura vigente), instead of the calendar month.
    planning_inv = planning_invoice_for_month(session, year_month, today=today)

    # Variable budgets must track the *fatura vigente* — the billing cycle that
    # is currently open/forming — rather than the calendar month or a
    # closed/official bill. The planning invoice exposes that cycle window both
    # for the current month (``open_invoice``) and for the vigente future month
    # (``active_open_invoice_transactions``); use it whenever present. Months
    # without an open cycle (official bills, scheduled installments, past
    # months) keep the calendar-month window unchanged.
    cycle_start_str = planning_inv.get("cycle_start")
    cycle_end_str = planning_inv.get("cycle_end")
    if cycle_start_str and cycle_end_str:
        vb_first_day = date.fromisoformat(cycle_start_str)
        vb_last_day = date.fromisoformat(cycle_end_str)
    else:
        vb_first_day = first_day
        vb_last_day = last_day

    variable_budgets = budget_progress_summary(
        session,
        year_month=year_month,
        first_day=vb_first_day,
        last_day=vb_last_day,
        today=today,
        fixed_cost_accounted_transaction_ids=fixed_cost_accounted_ids,
    )

    expected_income_total = Decimal(str(income["total"]))
    fixed_cost_total = Decimal(str(fixed["total"]))
    fixed_cost_planned_total = Decimal(str(fixed["planned_total"]))
    fixed_cost_actual_total = Decimal(str(fixed["actual_total"]))
    fixed_cost_pending_total = Decimal(str(fixed["pending_total"]))
    fixed_cost_variance_total = Decimal(str(fixed["variance_total"]))
    fixed_cost_positive_variance_total = Decimal(str(fixed["positive_variance_total"]))
    fixed_cost_negative_variance_total = Decimal(str(fixed["negative_variance_total"]))
    fixed_cost_reserved_total = Decimal(str(fixed["reserved_or_actual_total"]))
    card_invoice_gross_total = Decimal(str(invoice["invoice_gross_total"]))
    card_invoice_discretionary_total = Decimal(str(invoice["invoice_discretionary_total"]))
    card_invoice_total = card_invoice_discretionary_total
    invoice_paid_gross_total = Decimal(str(invoice["invoice_paid_gross_total"]))
    invoice_paid_discretionary_total = Decimal(str(invoice["invoice_paid_discretionary_total"]))
    invoice_open_gross_total = Decimal(str(invoice["invoice_open_gross_total"]))
    invoice_open_discretionary_total = Decimal(str(invoice["invoice_open_discretionary_total"]))
    invoice_paid_total = invoice_paid_discretionary_total
    invoice_open_total = invoice_open_discretionary_total
    card_invoice_fixed_cost_total = max(
        card_invoice_gross_total - card_invoice_discretionary_total,
        Decimal("0"),
    )

    card_invoice_source = planning_inv["source"]
    card_open_balance_total = Decimal(str(planning_inv["account_balance_total"]))
    credit_card_due_dates = planning_inv["due_dates"]
    variable_budget_total = Decimal(str(variable_budgets["summary"]["target"]))
    variable_budget_spent = Decimal(str(variable_budgets["summary"]["projected_spent"]))
    variable_budget_actual_spent = Decimal(str(variable_budgets["summary"]["actual_spent"]))
    variable_budget_future_spent = Decimal(str(variable_budgets["summary"]["future_spent"]))
    unbudgeted_variable_spent = Decimal(
        str(variable_budgets["summary"]["unbudgeted_projected_spent"])
    )
    variable_budget_consumed = Decimal(str(variable_budgets["summary"]["target_consumed"]))
    variable_budget_remaining = Decimal(str(variable_budgets["summary"]["target_remaining"]))
    variable_budget_overage = Decimal(str(variable_budgets["summary"]["target_overage"]))
    variable_budget_free_impact = Decimal(str(variable_budgets["summary"]["free_impact"]))
    received_income_transactions = []
    if first_day <= today:
        received_income_transactions = bank_income_transactions(
            session,
            first_day,
            min(last_day, today),
        )
    received_income_total = sum(
        (tx.amount for tx in received_income_transactions),
        Decimal("0"),
    )
    bank_inflow_txs = bank_inflow_transactions(session, first_day, min(last_day, today))
    bank_inflows_total = sum(
        (tx.amount for tx in bank_inflow_txs),
        Decimal("0"),
    )
    bank_outflow_txs = bank_outflow_transactions(session, first_day, min(last_day, today))
    bank_outflows_total = sum(
        (abs(tx.amount) for tx in bank_outflow_txs),
        Decimal("0"),
    )
    income_to_receive = max(
        expected_income_total - received_income_total,
        Decimal("0"),
    )
    income_over_expected = max(
        received_income_total - expected_income_total,
        Decimal("0"),
    )
    income_received_progress_pct = (
        (float(received_income_total) / float(expected_income_total)) * 100
        if expected_income_total > 0
        else None
    )

    planned_expense_total = fixed_cost_total + variable_budget_total
    planned_after_fixed_costs = expected_income_total - fixed_cost_total
    remaining_after_plan = expected_income_total - planned_expense_total

    current_ym = today.strftime("%Y-%m")
    if year_month == current_ym:
        planning_mode = "current_month"
    elif year_month > current_ym:
        planning_mode = "future_month"
    else:
        planning_mode = "past_month"
    is_future_month = planning_mode == "future_month"

    planning_inv_amount = Decimal(str(planning_inv["amount"]))
    if planning_inv["source"] in (
        "official_bill",
        "open_invoice",
        "active_open_invoice_transactions",
        "account_balance",
        "account_balance_due_month",
        "dashboard_current_invoice",
    ):
        card_invoice_official_total = planning_inv_amount
    elif planning_inv["source"] == "scheduled_installments":
        card_invoice_official_total = card_invoice_gross_total
    else:
        card_invoice_official_total = card_invoice_gross_total

    card_invoice_remaining_to_include = max(
        card_invoice_official_total - card_invoice_gross_total,
        Decimal("0"),
    )

    if planning_mode == "current_month":
        card_invoice_current_open_total = planning_inv_amount
        card_invoice_current_open_source = planning_inv["source"]
        card_invoice_current_open_label = planning_inv["source_label"]
        card_invoice_cycle_start = planning_inv.get("cycle_start")
        card_invoice_cycle_end = planning_inv.get("cycle_end")
        card_invoice_tx_count = planning_inv.get("transaction_count", 0)
    else:
        card_invoice_current_open_total = Decimal("0")
        card_invoice_current_open_source = "none"
        card_invoice_current_open_label = None
        card_invoice_cycle_start = None
        card_invoice_cycle_end = None
        card_invoice_tx_count = 0

    variable_budget_reserved = (
        variable_budget_total
        if planning_mode == "future_month"
        else variable_budget_consumed + variable_budget_overage
    )

    if planning_mode == "future_month":
        future_card_obligation_source = planning_inv["source"]
        future_card_obligation_count = planning_inv.get("transaction_count", 0)

        if planning_inv["source"] == "scheduled_installments":
            raw_installments = scheduled_installments_for_month(session, year_month, today=today)
            non_fixed_items = [
                item
                for item in raw_installments["transactions"]
                if item["transaction_id"] not in fixed_cost_accounted_ids
            ]
            non_fixed_total = sum(
                (Decimal(str(item["amount"])) for item in non_fixed_items),
                Decimal("0"),
            )
            if non_fixed_total > 0:
                future_card_obligation_total = non_fixed_total
                future_card_obligation_count = len(non_fixed_items)
            else:
                future_card_obligation_total = Decimal("0")
                future_card_obligation_source = "none"
                future_card_obligation_count = 0
        elif planning_inv["source"] in (
            "official_bill",
            "account_balance_due_month",
            "active_open_invoice_transactions",
            "dashboard_current_invoice",
        ):
            future_card_obligation_total = planning_inv_amount
        else:
            future_card_obligation_total = Decimal("0")
            future_card_obligation_source = "none"
            future_card_obligation_count = 0
    else:
        future_card_obligation_total = Decimal("0")
        future_card_obligation_source = "none"
        future_card_obligation_count = 0

    if future_card_obligation_source == "scheduled_installments":
        _ym_y, _ym_m = int(year_month[:4]), int(year_month[5:])
        if _ym_m == 12:
            future_card_obligation_display_month = f"{_ym_y + 1}-01"
        else:
            future_card_obligation_display_month = f"{_ym_y}-{_ym_m + 1:02d}"
    else:
        future_card_obligation_display_month = year_month

    if planning_mode == "future_month":
        budget_available_to_spend = (
            expected_income_total
            - fixed_cost_planned_total
            - variable_budget_total
            - future_card_obligation_total
        )
    else:
        budget_available_to_spend = (
            expected_income_total
            - fixed_cost_reserved_total
            - variable_budget_reserved
            - card_invoice_remaining_to_include
        )

    available_to_spend = budget_available_to_spend
    discretionary_available = budget_available_to_spend
    received_based_available_to_spend = (
        budget_available_to_spend - income_to_receive + income_over_expected
    )
    remaining_after_invoice = planned_after_fixed_costs - card_invoice_discretionary_total
    remaining_after_plan_and_invoice = remaining_after_plan - card_invoice_discretionary_total

    projected_cash_available: Optional[float] = None

    if today > last_day:
        days_remaining_in_month = 0
    elif today < first_day:
        days_remaining_in_month = (last_day - first_day).days + 1
    else:
        days_remaining_in_month = (last_day - today).days + 1
    if days_remaining_in_month > 0:
        daily_discretionary_remaining = max(budget_available_to_spend, Decimal("0")) / Decimal(
            days_remaining_in_month
        )
    else:
        daily_discretionary_remaining = Decimal("0")

    if expected_income_total <= 0:
        plan_status = "unknown"
    elif budget_available_to_spend < 0:
        plan_status = "over"
    elif (budget_available_to_spend / expected_income_total) < Decimal("0.10"):
        plan_status = "tight"
    else:
        plan_status = "healthy"

    return {
        "year_month": year_month,
        "planning_mode": planning_mode,
        "is_future_month": is_future_month,
        "planning_invoice": planning_inv,
        "expected_income_total": float(expected_income_total),
        "receita_esperada": float(expected_income_total),
        "received_income_total": float(received_income_total),
        "valor_recebido": float(received_income_total),
        "received_income_count": len(received_income_transactions),
        "bank_inflows_total": float(bank_inflows_total),
        "bank_outflows_total": float(bank_outflows_total),
        "income_to_receive": float(income_to_receive),
        "receita_a_receber": float(income_to_receive),
        "income_over_expected": float(income_over_expected),
        "income_received_progress_pct": income_received_progress_pct,
        "fixed_cost_total": float(fixed_cost_total),
        "fixed_cost_planned_total": float(fixed_cost_planned_total),
        "fixed_cost_actual_total": float(fixed_cost_actual_total),
        "fixed_cost_pending_total": float(fixed_cost_pending_total),
        "fixed_cost_variance_total": float(fixed_cost_variance_total),
        "fixed_cost_positive_variance_total": float(fixed_cost_positive_variance_total),
        "fixed_cost_negative_variance_total": float(fixed_cost_negative_variance_total),
        "fixed_cost_reserved_total": float(fixed_cost_reserved_total),
        "fixed_cost_paid_count": fixed["paid_count"],
        "fixed_cost_pending_count": fixed["pending_count"],
        "variable_budget_total": float(variable_budget_total),
        "planned_variable_total": float(variable_budget_total),
        "variable_budget_spent": float(variable_budget_spent),
        "variable_budget_actual_spent": float(variable_budget_actual_spent),
        "variable_budget_future_spent": float(variable_budget_future_spent),
        "variable_budget_consumed": float(variable_budget_consumed),
        "variable_budget_remaining": float(variable_budget_remaining),
        "variable_budget_overage": float(variable_budget_overage),
        "variable_budget_free_impact": float(variable_budget_free_impact),
        "variable_budget_reserved": float(variable_budget_reserved),
        "unbudgeted_variable_spent": float(unbudgeted_variable_spent),
        "discretionary_available": float(discretionary_available),
        "budget_available_to_spend": float(budget_available_to_spend),
        "projected_cash_available": projected_cash_available,
        "daily_discretionary_remaining": float(daily_discretionary_remaining),
        "days_remaining_in_month": days_remaining_in_month,
        "plan_status": plan_status,
        "planned_expense_total": float(planned_expense_total),
        "card_invoice_total": float(card_invoice_total),
        "card_invoice_gross_total": float(card_invoice_gross_total),
        "card_invoice_discretionary_total": float(card_invoice_discretionary_total),
        "card_invoice_fixed_cost_total": float(card_invoice_fixed_cost_total),
        "card_invoice_official_total": float(card_invoice_official_total),
        "card_invoice_remaining_to_include": float(card_invoice_remaining_to_include),
        "future_card_obligation_total": float(future_card_obligation_total),
        "future_card_obligation_source": future_card_obligation_source,
        "future_card_obligation_count": future_card_obligation_count,
        "future_card_obligation_display_month": future_card_obligation_display_month,
        "card_invoice_source": card_invoice_source,
        "card_invoice_current_open_total": float(card_invoice_current_open_total),
        "card_invoice_current_open_source": card_invoice_current_open_source,
        "card_invoice_current_open_label": card_invoice_current_open_label,
        "card_invoice_cycle_start": card_invoice_cycle_start,
        "card_invoice_cycle_end": card_invoice_cycle_end,
        "card_invoice_transaction_count": card_invoice_tx_count,
        "card_open_balance_total": float(card_open_balance_total),
        "credit_card_due_dates": credit_card_due_dates,
        "invoice_paid_total": float(invoice_paid_total),
        "invoice_open_total": float(invoice_open_total),
        "invoice_paid_gross_total": float(invoice_paid_gross_total),
        "invoice_paid_discretionary_total": float(invoice_paid_discretionary_total),
        "invoice_open_gross_total": float(invoice_open_gross_total),
        "invoice_open_discretionary_total": float(invoice_open_discretionary_total),
        "invoice_mode": invoice["invoice_mode"],
        "invoice_paid_count": invoice["invoice_paid_count"],
        "invoice_open_count": invoice["invoice_open_count"],
        "invoice_gross_count": invoice["invoice_gross_count"],
        "invoice_discretionary_count": invoice["invoice_discretionary_count"],
        "invoice_open_since": invoice["invoice_open_since"],
        "planned_after_fixed_costs": float(planned_after_fixed_costs),
        "remaining_after_plan": float(remaining_after_plan),
        "available_to_spend": float(available_to_spend),
        "received_based_available_to_spend": float(received_based_available_to_spend),
        "remaining_after_invoice": float(remaining_after_invoice),
        "remaining_after_plan_and_invoice": float(remaining_after_plan_and_invoice),
        "fixed_costs": fixed,
        "expected_income": income,
        "variable_budgets": variable_budgets,
    }


def spending_capacity_monthly_summary(
    session: Session,
    months: int = 12,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    if not (1 <= months <= 24):
        raise FixedCostValidationError("months must be between 1 and 24")
    today = today if today is not None else date.today()
    current_month = today.strftime("%Y-%m")
    start_month = _shift_year_month(current_month, -(months - 1))

    rows: list[Dict[str, Any]] = []
    totals = {
        "expected_income_total": Decimal("0"),
        "received_income_total": Decimal("0"),
        "income_to_receive": Decimal("0"),
        "bank_inflows_total": Decimal("0"),
        "bank_outflows_total": Decimal("0"),
        "fixed_cost_total": Decimal("0"),
        "fixed_cost_planned_total": Decimal("0"),
        "fixed_cost_actual_total": Decimal("0"),
        "fixed_cost_pending_total": Decimal("0"),
        "fixed_cost_variance_total": Decimal("0"),
        "fixed_cost_reserved_total": Decimal("0"),
        "variable_budget_total": Decimal("0"),
        "variable_budget_spent": Decimal("0"),
        "variable_budget_consumed": Decimal("0"),
        "variable_budget_remaining": Decimal("0"),
        "variable_budget_overage": Decimal("0"),
        "card_invoice_gross_total": Decimal("0"),
        "card_invoice_discretionary_total": Decimal("0"),
        "card_invoice_fixed_cost_total": Decimal("0"),
        "card_invoice_remaining_to_include": Decimal("0"),
        "budget_available_to_spend": Decimal("0"),
        "discretionary_available": Decimal("0"),
    }
    for offset in range(months):
        year_month = _shift_year_month(start_month, offset)
        capacity = spending_capacity_summary(session, year_month, today=today)
        row = {
            "year_month": year_month,
            "month": year_month,
            "expected_income_total": capacity["expected_income_total"],
            "received_income_total": capacity["received_income_total"],
            "income_to_receive": capacity["income_to_receive"],
            "bank_inflows_total": capacity["bank_inflows_total"],
            "bank_outflows_total": capacity["bank_outflows_total"],
            "fixed_cost_total": capacity["fixed_cost_total"],
            "fixed_cost_planned_total": capacity["fixed_cost_planned_total"],
            "fixed_cost_actual_total": capacity["fixed_cost_actual_total"],
            "fixed_cost_pending_total": capacity["fixed_cost_pending_total"],
            "fixed_cost_variance_total": capacity["fixed_cost_variance_total"],
            "fixed_cost_reserved_total": capacity["fixed_cost_reserved_total"],
            "variable_budget_total": capacity["variable_budget_total"],
            "variable_budget_spent": capacity["variable_budget_spent"],
            "variable_budget_consumed": capacity["variable_budget_consumed"],
            "variable_budget_remaining": capacity["variable_budget_remaining"],
            "variable_budget_overage": capacity["variable_budget_overage"],
            "card_invoice_gross_total": capacity["card_invoice_gross_total"],
            "card_invoice_discretionary_total": capacity["card_invoice_discretionary_total"],
            "card_invoice_fixed_cost_total": capacity["card_invoice_fixed_cost_total"],
            "card_invoice_remaining_to_include": capacity["card_invoice_remaining_to_include"],
            "budget_available_to_spend": capacity["budget_available_to_spend"],
            "discretionary_available": capacity["discretionary_available"],
            "projected_cash_available": capacity["projected_cash_available"],
            "daily_discretionary_remaining": capacity["daily_discretionary_remaining"],
            "days_remaining_in_month": capacity["days_remaining_in_month"],
            "plan_status": capacity["plan_status"],
        }
        rows.append(row)
        for key in totals:
            totals[key] += Decimal(str(row[key]))

    return {
        "months": rows,
        "month_count": len(rows),
        "summary": {key: float(value) for key, value in totals.items()},
    }
