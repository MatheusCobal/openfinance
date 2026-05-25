from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

MAX_BUDGET_MONTH = 2100
MIN_BUDGET_MONTH = 2000


def month_range(year_month: Optional[str] = None) -> tuple[str, date, date]:
    if year_month is None:
        year_month = date.today().strftime("%Y-%m")
    parts = year_month.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise HTTPException(400, "year_month must use YYYY-MM format")
    try:
        year = int(parts[0])
        month = int(parts[1])
        if year < MIN_BUDGET_MONTH or year > MAX_BUDGET_MONTH:
            raise ValueError
        last_day = monthrange(year, month)[1]
        return year_month, date(year, month, 1), date(year, month, last_day)
    except ValueError:
        raise HTTPException(400, "year_month must be a valid calendar month")


def validate_budget_target(monthly_target: Decimal) -> None:
    if monthly_target <= 0:
        raise HTTPException(400, "monthly_target must be > 0")
