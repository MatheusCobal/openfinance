from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import Investment, InvestmentTransaction
from app.services.pluggy_snapshot import (
    has_any_investments,
    reserve_investments,
    reserve_total_from_investments,
)
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


def _empty_totals() -> Dict[str, Decimal]:
    return {
        "applications": Decimal("0"),
        "rescues": Decimal("0"),
        "taxes": Decimal("0"),
        "net": Decimal("0"),
    }


def _pluggy_monthly_summary(
    session: Session,
    keys: List[str],
    today: date,
) -> Dict[str, Any]:
    """Reserve movements derived from Pluggy InvestmentTransaction rows.

    - applications = BUY
    - rescues      = SELL
    - taxes        = TAX
    Current reserve balance is Investment.balance (point-in-time), not a
    cumulative of movements — that's the whole point of using the snapshot.
    """
    reserve_invs = reserve_investments(session)
    reserve_ids = {inv.id for inv in reserve_invs}
    current_reserve_balance = reserve_total_from_investments(session)

    inv_txs: List[InvestmentTransaction] = []
    if reserve_ids:
        inv_txs = list(
            session.exec(
                select(InvestmentTransaction).where(
                    InvestmentTransaction.investment_id.in_(reserve_ids)
                )
            ).all()
        )

    rows: list[Dict[str, Any]] = []
    totals = _empty_totals()
    cumulative_net = Decimal("0")
    for year_month in keys:
        first_day, last_day = _month_bounds(year_month)
        window_end = min(last_day, today)

        applications_total = Decimal("0")
        rescues_total = Decimal("0")
        taxes_total = Decimal("0")
        transactions: list[Dict[str, Any]] = []
        application_count = 0
        rescue_count = 0
        tax_count = 0

        for tx in inv_txs:
            if tx.date is None or not (first_day <= tx.date <= window_end):
                continue
            amount = abs(tx.amount) if tx.amount is not None else Decimal("0")
            tx_type = (tx.type or "").upper()
            if tx_type == "BUY":
                direction = "application"
                applications_total += amount
                application_count += 1
            elif tx_type == "SELL":
                direction = "rescue"
                rescues_total += amount
                rescue_count += 1
            elif tx_type == "TAX":
                direction = "tax"
                taxes_total += amount
                tax_count += 1
            else:
                # TRANSFER / unknown — show it but don't move the net.
                direction = "transfer"
            transactions.append({
                "id": tx.id,
                "date": tx.date.isoformat(),
                "amount": float(amount),
                "direction": direction,
                "description": tx.description,
                "category": tx_type or None,
            })

        net = applications_total - rescues_total
        cumulative_net += net
        totals["applications"] += applications_total
        totals["rescues"] += rescues_total
        totals["taxes"] += taxes_total
        totals["net"] += net
        transactions.sort(key=lambda t: t["date"])

        rows.append({
            "year_month": year_month,
            "month": year_month,
            "applications_total": float(applications_total),
            "rescues_total": float(rescues_total),
            "taxes_total": float(taxes_total),
            "net_total": float(net),
            "cumulative_net_total": float(cumulative_net),
            "application_count": application_count,
            "rescue_count": rescue_count,
            "tax_count": tax_count,
            "transactions": transactions,
        })

    return {
        "source": "pluggy",
        "current_reserve_balance": float(current_reserve_balance),
        "reserve_investment_count": len(reserve_invs),
        "months": rows,
        "month_count": len(rows),
        "summary": {
            "applications_total": float(totals["applications"]),
            "rescues_total": float(totals["rescues"]),
            "taxes_total": float(totals["taxes"]),
            "net_total": float(totals["net"]),
            "cumulative_net_total": float(cumulative_net),
            "current_reserve_balance": float(current_reserve_balance),
        },
    }


def _transactions_monthly_summary(
    session: Session,
    keys: List[str],
    today: date,
) -> Dict[str, Any]:
    """Legacy fallback: reserve derived from bank "Fixed income" transactions.

    Only used when no Pluggy Investment rows exist for the user, so the
    feature still works on connectors that don't expose the investments
    product. ``source`` is labelled ``"transactions"`` so the UI can show
    it's an approximation.
    """
    rows: list[Dict[str, Any]] = []
    totals = _empty_totals()
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
            "taxes_total": 0.0,
            "net_total": float(net),
            "cumulative_net_total": float(cumulative_net),
            "application_count": len(applications),
            "rescue_count": len(rescues),
            "tax_count": 0,
            "transactions": transactions,
        })

    return {
        "source": "transactions",
        # No reliable point-in-time balance from transactions alone — the
        # cumulative net of the window is the best proxy we can offer.
        "current_reserve_balance": float(cumulative_net),
        "reserve_investment_count": 0,
        "months": rows,
        "month_count": len(rows),
        "summary": {
            "applications_total": float(totals["applications"]),
            "rescues_total": float(totals["rescues"]),
            "taxes_total": 0.0,
            "net_total": float(totals["net"]),
            "cumulative_net_total": float(cumulative_net),
            "current_reserve_balance": float(cumulative_net),
        },
    }


def reserve_applied_in_month(
    session: Session,
    first_day: date,
    last_day: date,
    today: date,
) -> Decimal:
    """Gross reserve application total for [first_day, last_day] ∩ [−∞, today].

    Source priority (mirrors emergency_reserve_monthly_summary):
      1. InvestmentTransaction BUY rows for reserve investments (Pluggy path).
      2. Bank "Fixed income" application transactions (legacy fallback).

    Only the gross inflow into the reserve is counted — rescues are a separate
    decision and do not reduce this value.
    """
    if first_day > today:
        return Decimal("0")
    window_end = min(last_day, today)

    if has_any_investments(session):
        reserve_invs = reserve_investments(session)
        reserve_ids = {inv.id for inv in reserve_invs}
        if not reserve_ids:
            return Decimal("0")
        inv_txs = session.exec(
            select(InvestmentTransaction).where(
                InvestmentTransaction.investment_id.in_(reserve_ids),
                InvestmentTransaction.date >= first_day,
                InvestmentTransaction.date <= window_end,
                InvestmentTransaction.type == "BUY",
            )
        ).all()
        return sum(
            (abs(tx.amount) for tx in inv_txs if tx.amount is not None),
            Decimal("0"),
        )

    # Fallback: bank "Fixed income" category outflows
    applications = investment_application_transactions(session, first_day, window_end)
    return sum((abs(tx.amount) for tx in applications), Decimal("0"))


def emergency_reserve_monthly_summary(
    session: Session,
    months: int = 6,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Per-month breakdown of reserve movements.

    Source of truth, in priority order:
      1. Pluggy Investment + InvestmentTransaction (BUY/SELL/TAX) — preferred
         whenever any Investment row exists. ``current_reserve_balance`` comes
         straight from ``Investment.balance``.
      2. Bank "Fixed income" transactions — legacy fallback, only when no
         investments are available. Labelled ``source: "transactions"``.
    """
    if not (1 <= months <= 24):
        raise ValueError("months must be between 1 and 24")
    today = today if today is not None else date.today()
    keys = last_month_keys(months, today)

    if has_any_investments(session):
        return _pluggy_monthly_summary(session, keys, today)
    return _transactions_monthly_summary(session, keys, today)
