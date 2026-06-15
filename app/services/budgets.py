from datetime import date
from typing import Any, Dict, Optional, Set

from sqlmodel import Session


def budget_status(progress_pct: Optional[float]) -> Optional[str]:
    if progress_pct is None:
        return None
    if progress_pct >= 100:
        return "over"
    if progress_pct >= 80:
        return "warning"
    return "ok"


def budget_progress_summary(
    session: Session,
    year_month: str,
    first_day: date,
    last_day: date,
    today: date,
    include_ignored: bool = False,
    fixed_cost_accounted_transaction_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    # 10D-C: variable budgets are now rebuilt on top of the Pluggy-based
    # classification (see app.services.variable_budgets). The response shape is
    # preserved — ``summary`` keeps every key spending_capacity consumes, and
    # ``items`` carries the per-category goals/spend for the Planejamento tab.
    from app.services.variable_budgets import variable_budget_progress

    if fixed_cost_accounted_transaction_ids is None:
        from app.services.fixed_costs import accounted_transaction_ids_for_month

        fixed_cost_accounted_transaction_ids = accounted_transaction_ids_for_month(
            session, year_month
        )

    return variable_budget_progress(
        session,
        year_month=year_month,
        first_day=first_day,
        last_day=last_day,
        today=today,
        exclude_transaction_ids=set(fixed_cost_accounted_transaction_ids),
    )
