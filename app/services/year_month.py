import re
from datetime import date, timedelta

YEAR_MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")


class InvalidYearMonth(ValueError):
    """Raised when a value is not a real calendar month in YYYY-MM form."""


def parse_year_month(value: str) -> tuple[int, int]:
    match = YEAR_MONTH_PATTERN.fullmatch(value)
    if match is None:
        raise InvalidYearMonth("year_month must be in YYYY-MM format")
    year = int(match.group("year"))
    month = int(match.group("month"))
    try:
        date(year, month, 1)
    except ValueError as exc:
        raise InvalidYearMonth("year_month must be in YYYY-MM format") from exc
    return year, month


def month_bounds(value: str) -> tuple[date, date]:
    year, month = parse_year_month(value)
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return first_day, next_month - timedelta(days=1)


def shift_year_month(value: str, months: int) -> str:
    year, month = parse_year_month(value)
    absolute_month = year * 12 + month - 1 + months
    shifted_year, shifted_month_index = divmod(absolute_month, 12)
    if shifted_year < 1 or shifted_year > 9999:
        raise InvalidYearMonth("shifted year_month is outside the supported range")
    return f"{shifted_year:04d}-{shifted_month_index + 1:02d}"
