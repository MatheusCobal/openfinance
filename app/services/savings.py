from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import SavingsTarget, SavingsTargetOverride


class SavingsTargetValidationError(ValueError):
    pass


def _validate_month(year_month: str) -> None:
    try:
        year_str, month_str = year_month.split("-")
        year = int(year_str)
        month = int(month_str)
        if not (1 <= month <= 12) or year < 1900:
            raise ValueError
    except (ValueError, AttributeError):
        raise SavingsTargetValidationError("year_month must be in YYYY-MM format")


def _validate_amount(amount: Decimal) -> None:
    if amount is None or amount < 0:
        raise SavingsTargetValidationError("monthly_target must be non-negative")


def _get_default(session: Session) -> Optional[SavingsTarget]:
    return session.exec(select(SavingsTarget)).first()


def get_default(session: Session) -> Dict[str, Any]:
    target = _get_default(session)
    return {
        "monthly_target": float(target.monthly_target) if target else 0.0,
    }


def set_default(session: Session, amount: Decimal) -> Dict[str, Any]:
    _validate_amount(amount)
    target = _get_default(session)
    if target is None:
        target = SavingsTarget(monthly_target=amount)
    else:
        target.monthly_target = amount
    session.add(target)
    session.commit()
    session.refresh(target)
    return {"monthly_target": float(target.monthly_target)}


def clear_default(session: Session) -> bool:
    target = _get_default(session)
    if target is None:
        return False
    session.delete(target)
    session.commit()
    return True


def get_override(
    session: Session, year_month: str
) -> Optional[SavingsTargetOverride]:
    _validate_month(year_month)
    return session.exec(
        select(SavingsTargetOverride).where(
            SavingsTargetOverride.year_month == year_month
        )
    ).first()


def set_override(
    session: Session, year_month: str, amount: Decimal
) -> Dict[str, Any]:
    _validate_month(year_month)
    _validate_amount(amount)
    existing = get_override(session, year_month)
    if existing is None:
        existing = SavingsTargetOverride(
            year_month=year_month, monthly_target=amount
        )
    else:
        existing.monthly_target = amount
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return {
        "year_month": existing.year_month,
        "monthly_target": float(existing.monthly_target),
    }


def delete_override(session: Session, year_month: str) -> bool:
    existing = get_override(session, year_month)
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def effective_target(session: Session, year_month: str) -> Decimal:
    """Return the savings target that applies to ``year_month``.

    Per-month override wins over the default. Returns 0 when neither is set.
    """
    override = get_override(session, year_month)
    if override is not None:
        return override.monthly_target
    default = _get_default(session)
    return default.monthly_target if default is not None else Decimal("0")


def monthly_breakdown(session: Session, year_month: str) -> Dict[str, Any]:
    _validate_month(year_month)
    default = _get_default(session)
    override = get_override(session, year_month)
    default_amount = default.monthly_target if default is not None else Decimal("0")
    effective_amount = (
        override.monthly_target if override is not None else default_amount
    )
    return {
        "year_month": year_month,
        "default_target": float(default_amount),
        "monthly_target": float(effective_amount),
        "is_override": override is not None,
        "scope": "month" if override is not None else "default",
    }
