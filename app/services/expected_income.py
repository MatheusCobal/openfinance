from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import BankIncomeMonth, ExpectedIncome
from app.services.history import refresh_bank_income_snapshots


class ExpectedIncomeValidationError(ValueError):
    pass


def _validate(description: Optional[str], amount: Decimal, expected_day: int) -> None:
    if not description or not description.strip():
        raise ExpectedIncomeValidationError("description must not be empty")
    if amount <= 0:
        raise ExpectedIncomeValidationError("amount must be positive")
    if not (1 <= expected_day <= 31):
        raise ExpectedIncomeValidationError("expected_day must be between 1 and 31")


def _serialize(entry: ExpectedIncome) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "description": entry.description,
        "amount": float(entry.amount),
        "expected_day": entry.expected_day,
        "active": entry.active,
    }


def list_expected_income(
    session: Session, include_inactive: bool = False
) -> List[Dict[str, Any]]:
    query = select(ExpectedIncome).order_by(
        ExpectedIncome.expected_day, ExpectedIncome.description
    )
    if not include_inactive:
        query = query.where(ExpectedIncome.active.is_(True))
    return [_serialize(entry) for entry in session.exec(query).all()]


def create_expected_income(
    session: Session,
    description: str,
    amount: Decimal,
    expected_day: int,
) -> Dict[str, Any]:
    _validate(description, amount, expected_day)
    entry = ExpectedIncome(
        description=description.strip(),
        amount=amount,
        expected_day=expected_day,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _serialize(entry)


def update_expected_income(
    session: Session,
    entry_id: int,
    description: Optional[str] = None,
    amount: Optional[Decimal] = None,
    expected_day: Optional[int] = None,
    active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    entry = session.get(ExpectedIncome, entry_id)
    if entry is None:
        return None

    new_desc = description.strip() if description is not None else entry.description
    new_amount = amount if amount is not None else entry.amount
    new_day = expected_day if expected_day is not None else entry.expected_day
    _validate(new_desc, new_amount, new_day)

    entry.description = new_desc
    entry.amount = new_amount
    entry.expected_day = new_day
    if active is not None:
        entry.active = active
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _serialize(entry)


def delete_expected_income(session: Session, entry_id: int) -> bool:
    entry = session.get(ExpectedIncome, entry_id)
    if entry is None:
        return False
    session.delete(entry)
    session.commit()
    return True


def _parse_year_month(year_month: str) -> tuple[int, int]:
    try:
        year_str, month_str = year_month.split("-")
        year = int(year_str)
        month = int(month_str)
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise ExpectedIncomeValidationError(
            "year_month must be in YYYY-MM format"
        )
    return year, month


def expected_income_forecast(
    session: Session, year_month: str, today: Optional[date] = None
) -> Dict[str, Any]:
    year, month = _parse_year_month(year_month)
    today = today or date.today()

    # Refresh just the snapshot for the target month so the figure is fresh
    # without paying for a full backfill.
    refresh_bank_income_snapshots(session, months=1)
    snapshot = session.get(BankIncomeMonth, year_month)
    received_total = snapshot.total if snapshot is not None else Decimal("0")
    received_count = snapshot.income_count if snapshot is not None else 0

    entries = session.exec(
        select(ExpectedIncome)
        .where(ExpectedIncome.active.is_(True))
        .order_by(ExpectedIncome.expected_day, ExpectedIncome.description)
    ).all()
    expected_total = sum((entry.amount for entry in entries), Decimal("0"))
    remaining = expected_total - received_total
    if remaining < 0:
        remaining = Decimal("0")

    # Mark per-entry whether its expected day has already passed in the
    # current month — useful UX hint without trying to match per-entry.
    is_current_month = (today.year == year and today.month == month)
    items = []
    for entry in entries:
        items.append(
            {
                **_serialize(entry),
                "due_passed": is_current_month and entry.expected_day < today.day,
            }
        )

    return {
        "year_month": year_month,
        "expected_total": float(expected_total),
        "received_total": float(received_total),
        "received_count": received_count,
        "remaining_estimate": float(remaining),
        "entries": items,
    }
