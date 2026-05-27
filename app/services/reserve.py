from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session

from app.services.transactions import (
    investment_application_transactions,
    investment_rescue_transactions,
    last_month_keys,
)


def _month_bounds(year_month: str) -> tuple[date, date]:
    year_str, month_str = year_month.split("-")
    year = int(year_str)
    month = int(month_str)
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def emergency_reserve_monthly_summary(
    session: Session,
    months: int = 6,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Per-month breakdown of investment movements (CDB applications + rescues).

    For each month in the window:
      - applications: money invested (outflows tagged Fixed income)
      - rescues:      money withdrawn from investments
      - net:          applications - rescues (positive = net saved)
      - transactions: itemized list

    Plus a running cumulative_net so the user sees how the reserve grew
    over the window.
    """
    if not (1 <= months <= 24):
        raise ValueError("months must be between 1 and 24")
    today = today if today is not None else date.today()
    keys = last_month_keys(months, today)

    rows: list[Dict[str, Any]] = []
    totals = {
        "applications": Decimal("0"),
        "rescues": Decimal("0"),
        "net": Decimal("0"),
    }
    cumulative_net = Decimal("0")
    for year_month in keys:
        first_day, last_day = _month_bounds(year_month)
        window_end = min(last_day, today)
        applications = []
        rescues = []
        if first_day <= today:
            applications = investment_application_transactions(
                session, first_day, window_end
            )
            rescues = investment_rescue_transactions(
                session, first_day, window_end
            )
        applications_total = sum(
            (abs(tx.amount) for tx in applications), Decimal("0")
        )
        rescues_total = sum((tx.amount for tx in rescues), Decimal("0"))
        net = applications_total - rescues_total
        cumulative_net += net
        totals["applications"] += applications_total
        totals["rescues"] += rescues_total
        totals["net"] += net

        transactions = []
        for tx in applications:
            transactions.append({
                "id": tx.id,
                "date": tx.date.isoformat(),
                "amount": float(abs(tx.amount)),
                "direction": "application",
                "description": tx.description,
                "category": tx.category,
            })
        for tx in rescues:
            transactions.append({
                "id": tx.id,
                "date": tx.date.isoformat(),
                "amount": float(tx.amount),
                "direction": "rescue",
                "description": tx.description,
                "category": tx.category,
            })
        transactions.sort(key=lambda t: t["date"])

        rows.append({
            "year_month": year_month,
            "month": year_month,
            "applications_total": float(applications_total),
            "rescues_total": float(rescues_total),
            "net_total": float(net),
            "cumulative_net_total": float(cumulative_net),
            "application_count": len(applications),
            "rescue_count": len(rescues),
            "transactions": transactions,
        })

    return {
        "months": rows,
        "month_count": len(rows),
        "summary": {
            "applications_total": float(totals["applications"]),
            "rescues_total": float(totals["rescues"]),
            "net_total": float(totals["net"]),
            "cumulative_net_total": float(cumulative_net),
        },
    }
