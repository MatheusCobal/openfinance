import calendar
from datetime import date


def invoice_month_from_payment(payment_date: date, due_day: int) -> str:
    """Return the YYYY-MM of the invoice that a payment belongs to.

    The invoice month is the month containing the nearest due date that falls
    on or after the payment date.
    """
    max_day = calendar.monthrange(payment_date.year, payment_date.month)[1]
    candidate_day = min(due_day, max_day)
    candidate = payment_date.replace(day=candidate_day)
    if candidate >= payment_date:
        return candidate.strftime("%Y-%m")
    if payment_date.month == 12:
        return f"{payment_date.year + 1}-01"
    return f"{payment_date.year}-{payment_date.month + 1:02d}"
