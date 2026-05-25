import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.categorization import CategoryResolver
from app.database import get_session
from app.services.transaction_reports import (
    enriched_transactions,
    monthly_stats_summary,
    stats_summary,
    transaction_csv_rows,
    upcoming_summary,
)

router = APIRouter()


@router.get("/transactions")
def list_transactions(
    account_id: Optional[str] = None,
    account_type: Optional[str] = "CREDIT",
    category_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    try:
        return enriched_transactions(
            session,
            account_id=account_id,
            account_type=account_type,
            category_id=category_id,
            from_date=from_date,
            to_date=to_date,
            include_future=include_future,
            include_ignored=include_ignored,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/categories")
def list_categories(session: Session = Depends(get_session)):
    return CategoryResolver(session).all_categories()


@router.get("/export/transactions.csv")
def export_transactions_csv(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in transaction_csv_rows(
            session,
            from_date=from_date,
            to_date=to_date,
            include_future=include_future,
            include_ignored=include_ignored,
        ):
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()

    filename = f"transactions-{date.today().isoformat()}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/upcoming")
def upcoming(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    return upcoming_summary(session, include_ignored=include_ignored)


@router.get("/stats/monthly")
def stats_monthly(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    return monthly_stats_summary(session, include_ignored=include_ignored)


@router.get("/stats")
def stats(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    return stats_summary(
        session,
        from_date=from_date,
        to_date=to_date,
        include_ignored=include_ignored,
    )
