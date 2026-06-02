from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.models import Account, AccountSync, CreditCardBill, Item, Transaction


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _latest_datetime(values: list[Optional[datetime]]) -> Optional[datetime]:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _last_sync_duration_seconds(items: list[Item]) -> Optional[float]:
    finished_items = [
        item
        for item in items
        if item.sync_started_at is not None and item.sync_finished_at is not None
    ]
    if not finished_items:
        return None

    latest = max(finished_items, key=lambda item: item.sync_finished_at)
    duration = latest.sync_finished_at - latest.sync_started_at
    return max(duration.total_seconds(), 0)


def get_sync_status(session: Session) -> dict[str, Any]:
    items = list(session.exec(select(Item)).all())
    accounts = list(session.exec(select(Account)).all())
    account_syncs = list(session.exec(select(AccountSync)).all())
    transactions = list(session.exec(select(Transaction)).all())
    bills = list(session.exec(select(CreditCardBill)).all())

    running = any(
        item.sync_started_at is not None and item.sync_finished_at is None
        for item in items
    )
    item_errors = [item.last_sync_error for item in items if item.last_sync_error]
    account_errors = [sync.last_error for sync in account_syncs if sync.last_error]

    sync_timestamps = [item.sync_finished_at for item in items]
    sync_timestamps.extend(sync.last_synced_at for sync in account_syncs)
    last_sync_at = _latest_datetime(sync_timestamps)

    if running:
        last_sync_status = "running"
        last_sync_status_source = "item_sync_lock"
    elif item_errors or account_errors:
        last_sync_status = "error"
        last_sync_status_source = "persisted_error"
    elif last_sync_at is not None:
        last_sync_status = "success"
        last_sync_status_source = "estimated_from_sync_timestamps"
    else:
        last_sync_status = "unknown"
        last_sync_status_source = "not_tracked"

    last_sync_error = None
    if item_errors:
        last_sync_error = item_errors[-1]
    elif account_errors:
        last_sync_error = account_errors[-1]

    transaction_dates = [tx.date for tx in transactions]
    bill_due_dates = [bill.due_date for bill in bills if bill.due_date is not None]

    return {
        "last_sync_at": _iso(last_sync_at),
        "last_sync_status": last_sync_status,
        "last_sync_error": last_sync_error,
        "last_sync_status_source": last_sync_status_source,
        "last_sync_duration_seconds": _last_sync_duration_seconds(items),
        "items": {
            "total": len(items),
            "active": sum(1 for item in items if item.is_active),
            "inactive": sum(1 for item in items if not item.is_active),
            "updated": sum(1 for item in items if item.status == "UPDATED"),
            "error": len(item_errors),
        },
        "accounts": {
            "total": len(accounts),
            "active": sum(1 for account in accounts if account.is_active),
            "inactive": sum(1 for account in accounts if not account.is_active),
            "credit": sum(1 for account in accounts if account.type == "CREDIT"),
            "bank": sum(1 for account in accounts if account.type == "BANK"),
            "error": len(account_errors),
        },
        "transactions": {
            "total": len(transactions),
            "latest_date": _iso(max(transaction_dates)) if transaction_dates else None,
            "oldest_date": _iso(min(transaction_dates)) if transaction_dates else None,
        },
        "credit_card_bills": {
            "total": len(bills),
            "latest_due_date": _iso(max(bill_due_dates)) if bill_due_dates else None,
        },
    }
