from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, update
from sqlmodel import Session, select

from app.models import Account, AccountSync, Item, Transaction
from app.pluggy_client import pluggy
from app.services.snapshots import refresh_monthly_balance_snapshots
from app.services.transactions import TRACKED_ACCOUNT_TYPES

SYNC_LOOKBACK_DAYS = 7
SYNC_STALE_LOCK_MINUTES = 10
ERROR_MESSAGE_MAX_LEN = 500


class SyncAlreadyRunning(Exception):
    pass


def _truncate_error(exc: BaseException) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    return msg[:ERROR_MESSAGE_MAX_LEN]


@dataclass
class AccountSyncResult:
    fetched_transactions: int = 0
    new_transactions: int = 0
    updated_transactions: int = 0


def upsert_item(item_id: str, session: Session) -> Item:
    data = pluggy.get_item(item_id)
    item = session.get(Item, item_id)
    if item is None:
        item = Item(
            id=data["id"],
            connector_id=data["connector"]["id"],
            connector_name=data["connector"].get("name"),
            status=data["status"],
        )
        session.add(item)
    else:
        item.status = data["status"]
        item.connector_name = data["connector"].get("name")
    session.commit()
    session.refresh(item)
    return item


def upsert_account(raw_account: Dict[str, Any], item_id: str, session: Session) -> None:
    account = session.get(Account, raw_account["id"])
    values = {
        "item_id": item_id,
        "name": raw_account["name"],
        "type": raw_account["type"],
        "subtype": raw_account.get("subtype"),
        "marketing_name": raw_account.get("marketingName"),
        "number": raw_account.get("number"),
    }
    if account is None:
        session.add(Account(id=raw_account["id"], **values))
        return
    for field, value in values.items():
        setattr(account, field, value)
    session.add(account)


def last_past_transaction_date(
    account_id: str,
    session: Session,
) -> Optional[date]:
    return session.exec(
        select(Transaction.date)
        .where(
            Transaction.account_id == account_id,
            Transaction.date <= date.today(),
        )
        .order_by(Transaction.date.desc())
        .limit(1)
    ).first()


def sync_from_date(sync_state: AccountSync) -> Optional[date]:
    if sync_state.last_transaction_date is None:
        return None
    return sync_state.last_transaction_date - timedelta(days=SYNC_LOOKBACK_DAYS)


def upsert_transaction(
    raw_tx: Dict[str, Any],
    account_id: str,
    session: Session,
) -> tuple[bool, bool, date]:
    tx_date = date.fromisoformat(raw_tx["date"][:10])
    amount = Decimal(str(raw_tx["amount"]))
    values = {
        "account_id": account_id,
        "date": tx_date,
        "amount": amount,
        "description": raw_tx.get("description") or "",
        "category": raw_tx.get("category"),
        "currency_code": raw_tx.get("currencyCode") or "BRL",
    }
    existing = session.get(Transaction, raw_tx["id"])
    if existing is None:
        session.add(Transaction(id=raw_tx["id"], **values))
        return True, False, tx_date

    changed = False
    for field, value in values.items():
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed = True
    if changed:
        session.add(existing)
    return False, changed, tx_date


def tracked_accounts(raw_accounts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [
        account
        for account in raw_accounts
        if account["type"] in TRACKED_ACCOUNT_TYPES
    ]


def get_or_create_sync_state(account_id: str, session: Session) -> AccountSync:
    sync_state = session.get(AccountSync, account_id)
    if sync_state is not None:
        return sync_state

    sync_state = AccountSync(
        account_id=account_id,
        last_transaction_date=last_past_transaction_date(account_id, session),
    )
    session.add(sync_state)
    return sync_state


def sync_account_transactions(
    account_id: str,
    sync_state: AccountSync,
    session: Session,
) -> AccountSyncResult:
    result = AccountSyncResult()
    max_past_tx_date = sync_state.last_transaction_date
    for raw_tx in pluggy.list_transactions(
        account_id,
        from_date=sync_from_date(sync_state),
    ):
        result.fetched_transactions += 1
        is_new, is_updated, tx_date = upsert_transaction(
            raw_tx,
            account_id,
            session,
        )
        if is_new:
            result.new_transactions += 1
        if is_updated:
            result.updated_transactions += 1
        if tx_date <= date.today() and (
            max_past_tx_date is None or tx_date > max_past_tx_date
        ):
            max_past_tx_date = tx_date

    sync_state.last_transaction_date = max_past_tx_date
    sync_state.last_synced_at = datetime.utcnow()
    session.add(sync_state)
    return result


def _acquire_sync_lock(item_id: str, session: Session) -> datetime:
    # Atomic compare-and-swap: claim the lock only if it's free or stale.
    # rowcount tells us whether we actually acquired it.
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(minutes=SYNC_STALE_LOCK_MINUTES)
    stmt = (
        update(Item)
        .where(Item.id == item_id)
        .where(
            or_(
                Item.sync_started_at.is_(None),
                Item.sync_finished_at.is_not(None),
                Item.sync_started_at < stale_cutoff,
            )
        )
        .values(sync_started_at=now, sync_finished_at=None, last_sync_error=None)
    )
    result = session.exec(stmt)
    session.commit()
    if result.rowcount == 0:
        raise SyncAlreadyRunning(f"sync already running for item {item_id}")
    return now


def _release_sync_lock(
    item_id: str,
    session: Session,
    error: Optional[str] = None,
) -> None:
    session.exec(
        update(Item)
        .where(Item.id == item_id)
        .values(sync_finished_at=datetime.utcnow(), last_sync_error=error)
    )
    session.commit()


def _sync_one_account(
    raw_account: Dict[str, Any],
    item_id: str,
    session: Session,
) -> AccountSyncResult:
    account_id = raw_account["id"]
    upsert_account(raw_account, item_id, session)
    sync_state = get_or_create_sync_state(account_id, session)
    result = sync_account_transactions(account_id, sync_state, session)
    sync_state.last_error = None
    sync_state.last_error_at = None
    session.add(sync_state)
    return result


def _record_account_failure(
    account_id: str,
    session: Session,
    error: str,
) -> None:
    # Runs after rollback, so the AccountSync row may not exist yet.
    sync_state = session.get(AccountSync, account_id) or AccountSync(
        account_id=account_id
    )
    sync_state.last_error = error
    sync_state.last_error_at = datetime.utcnow()
    session.add(sync_state)
    session.commit()


def sync_item(item_id: str, session: Session) -> Dict[str, Any]:
    _acquire_sync_lock(item_id, session)
    try:
        result = _sync_item_locked(item_id, session)
    except BaseException as exc:
        # Releases on top-level failure (e.g., list_accounts errored before the
        # per-account loop) so the item doesn't stay locked.
        _release_sync_lock(item_id, session, error=_truncate_error(exc))
        raise
    _release_sync_lock(item_id, session)
    return result


def _sync_item_locked(item_id: str, session: Session) -> Dict[str, Any]:
    raw_accounts = pluggy.list_accounts(item_id)
    accounts_to_sync = tracked_accounts(raw_accounts)

    new_transactions = 0
    updated_transactions = 0
    fetched_transactions = 0
    synced_accounts_by_type: Dict[str, int] = {}
    failed_accounts: List[Dict[str, str]] = []
    for raw_account in accounts_to_sync:
        account_id = raw_account["id"]
        account_type = raw_account["type"]
        try:
            account_result = _sync_one_account(raw_account, item_id, session)
            session.commit()
        except Exception as exc:
            session.rollback()
            error = _truncate_error(exc)
            _record_account_failure(account_id, session, error)
            failed_accounts.append({"account_id": account_id, "error": error})
            continue

        synced_accounts_by_type[account_type] = (
            synced_accounts_by_type.get(account_type, 0) + 1
        )
        fetched_transactions += account_result.fetched_transactions
        new_transactions += account_result.new_transactions
        updated_transactions += account_result.updated_transactions

    # Snapshots aggregate from the DB, so partial failures still produce
    # meaningful numbers — just for the accounts that succeeded.
    refreshed_income_months, refreshed_invoice_months, refreshed_balance_months = (
        refresh_monthly_balance_snapshots(session)
    )
    return {
        "tracked_accounts": len(accounts_to_sync),
        "credit_accounts": synced_accounts_by_type.get("CREDIT", 0),
        "bank_accounts": synced_accounts_by_type.get("BANK", 0),
        "fetched_transactions": fetched_transactions,
        "new_transactions": new_transactions,
        "updated_transactions": updated_transactions,
        "refreshed_invoice_months": refreshed_invoice_months,
        "refreshed_income_months": refreshed_income_months,
        "refreshed_balance_months": refreshed_balance_months,
        "failed_accounts": failed_accounts,
    }
