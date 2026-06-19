from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import ExpectedIncome, ExpectedIncomeOverride
from app.services.scoping import scope_query
from app.services.transactions import bank_income_transactions


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
    session: Session,
    include_inactive: bool = False,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = scope_query(select(ExpectedIncome), ExpectedIncome.user_id, user_id).order_by(
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
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    _validate(description, amount, expected_day)
    entry = ExpectedIncome(
        description=description.strip(),
        amount=amount,
        expected_day=expected_day,
        user_id=user_id,
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
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    entry = session.get(ExpectedIncome, entry_id)
    if entry is None or (user_id is not None and entry.user_id != user_id):
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


def delete_expected_income(
    session: Session,
    entry_id: int,
    user_id: Optional[int] = None,
) -> bool:
    entry = session.get(ExpectedIncome, entry_id)
    if entry is None or (user_id is not None and entry.user_id != user_id):
        return False
    session.delete(entry)
    session.commit()
    return True


def _shift_year_month(year_month: str, months: int) -> str:
    year, month = _parse_year_month(year_month)
    zero_based = year * 12 + (month - 1) + months
    return f"{zero_based // 12:04d}-{(zero_based % 12) + 1:02d}"


def monthly_breakdown(
    session: Session,
    year_month: str,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    _parse_year_month(year_month)
    entries = session.exec(
        scope_query(
            select(ExpectedIncome).where(ExpectedIncome.active.is_(True)),
            ExpectedIncome.user_id,
            user_id,
        ).order_by(ExpectedIncome.expected_day, ExpectedIncome.description)
    ).all()
    overrides = {
        ov.expected_income_id: ov
        for ov in session.exec(
            scope_query(
                select(ExpectedIncomeOverride).where(
                    ExpectedIncomeOverride.year_month == year_month
                ),
                ExpectedIncomeOverride.user_id,
                user_id,
            )
        ).all()
    }

    items = []
    total = Decimal("0")
    for entry in entries:
        override = overrides.get(entry.id)
        effective = override.amount if override is not None else entry.amount
        total += effective
        items.append(
            {
                "expected_income_id": entry.id,
                "description": entry.description,
                "expected_day": entry.expected_day,
                "base_amount": float(entry.amount),
                "amount": float(effective),
                "is_override": override is not None,
                "override_id": override.id if override is not None else None,
            }
        )
    return {
        "year_month": year_month,
        "total": float(total),
        "entries": items,
    }


def upcoming_months(
    session: Session,
    start_year_month: str,
    months: int,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not (1 <= months <= 24):
        raise ExpectedIncomeValidationError("months must be between 1 and 24")
    return [
        monthly_breakdown(session, _shift_year_month(start_year_month, offset), user_id=user_id)
        for offset in range(months)
    ]


def set_override(
    session: Session,
    entry_id: int,
    year_month: str,
    amount: Decimal,
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    _parse_year_month(year_month)
    if amount < 0:
        raise ExpectedIncomeValidationError("amount must be non-negative")
    entry = session.get(ExpectedIncome, entry_id)
    if entry is None or (user_id is not None and entry.user_id != user_id):
        return None

    existing = session.exec(
        select(ExpectedIncomeOverride).where(
            ExpectedIncomeOverride.expected_income_id == entry_id,
            ExpectedIncomeOverride.year_month == year_month,
        )
    ).first()
    if existing is None:
        existing = ExpectedIncomeOverride(
            expected_income_id=entry_id,
            year_month=year_month,
            amount=amount,
            user_id=user_id,
        )
    else:
        existing.amount = amount
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return {
        "id": existing.id,
        "expected_income_id": existing.expected_income_id,
        "year_month": existing.year_month,
        "amount": float(existing.amount),
    }


def delete_override(
    session: Session,
    entry_id: int,
    year_month: str,
    user_id: Optional[int] = None,
) -> bool:
    _parse_year_month(year_month)
    existing = session.exec(
        scope_query(
            select(ExpectedIncomeOverride).where(
                ExpectedIncomeOverride.expected_income_id == entry_id,
                ExpectedIncomeOverride.year_month == year_month,
            ),
            ExpectedIncomeOverride.user_id,
            user_id,
        )
    ).first()
    if existing is None:
        return False
    session.delete(existing)
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
        raise ExpectedIncomeValidationError("year_month must be in YYYY-MM format")
    return year, month


def expected_income_forecast(
    session: Session,
    year_month: str,
    today: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    year, month = _parse_year_month(year_month)
    today = today or date.today()

    first_day = date(year, month, 1)
    if today < first_day:
        received_transactions = []
    else:
        import calendar

        last_day = date(year, month, calendar.monthrange(year, month)[1])
        received_transactions = bank_income_transactions(
            session,
            first_day,
            min(last_day, today),
            user_id=user_id,
        )
    received_total = sum((tx.amount for tx in received_transactions), Decimal("0"))
    received_count = len(received_transactions)

    entries = session.exec(
        scope_query(
            select(ExpectedIncome).where(ExpectedIncome.active.is_(True)),
            ExpectedIncome.user_id,
            user_id,
        ).order_by(ExpectedIncome.expected_day, ExpectedIncome.description)
    ).all()
    expected_total = sum((entry.amount for entry in entries), Decimal("0"))
    remaining = expected_total - received_total
    if remaining < 0:
        remaining = Decimal("0")

    # Mark per-entry whether its expected day has already passed in the
    # current month — useful UX hint without trying to match per-entry.
    is_current_month = today.year == year and today.month == month
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
