import datetime
from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.categorization import CategoryResolver
from app.database import get_session
from app.models import Account
from app.pluggy_client import pluggy
from app.services.transaction_reports import (
    enriched_transactions,
    monthly_stats_summary,
    stats_summary,
    upcoming_summary,
    validate_account_type,
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


@router.post("/accounts/{account_id}/refresh-balance")
def refresh_balance(account_id: str, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, f"account {account_id} not found")
    try:
        data = pluggy.get_account_balance(account_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 405, 501):
            raise HTTPException(
                503,
                f"real-time balance not supported for account {account_id}",
            ) from exc
        if exc.response.status_code == 429:
            raise HTTPException(429, "rate limited by Pluggy") from exc
        raise HTTPException(502, f"Pluggy error: {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"network error reaching Pluggy: {exc}") from exc

    from decimal import Decimal, InvalidOperation
    raw_balance = data.get("balance")
    if raw_balance is not None:
        try:
            account.balance = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError):
            pass
    raw_updated = data.get("updatedAt") or data.get("date")
    if raw_updated:
        try:
            account.balance_updated_at = datetime.datetime.fromisoformat(
                str(raw_updated).replace("Z", "+00:00")
            )
        except ValueError:
            pass
    session.add(account)
    session.commit()
    session.refresh(account)
    return {
        "account_id": account_id,
        "balance": float(account.balance) if account.balance is not None else None,
        "balance_updated_at": (
            account.balance_updated_at.isoformat() if account.balance_updated_at else None
        ),
    }
