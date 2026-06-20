import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, update
from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, AccountSync, Item, Transaction
from app.pluggy_client import pluggy
from app.services.pluggy_snapshot import (
    account_snapshot_values,
    sync_credit_card_bills,
    sync_investments,
)
from app.services.snapshots import refresh_monthly_balance_snapshots
from app.services.transaction_classifier import (
    classification_payload_fields,
    classify_pluggy_payload,
)
from app.services.transactions import TRACKED_ACCOUNT_TYPES

SYNC_LOOKBACK_DAYS = 7
SYNC_STALE_LOCK_MINUTES = 10
ERROR_MESSAGE_MAX_LEN = 500


def compute_dedupe_key(
    account_type: str,
    description: str,
    tx_date: date,
    amount: Decimal,
    installment_number: Optional[int],
    total_installments: Optional[int],
) -> str:
    """Stable hash of the transaction's natural key.

    Used to detect the same real-world purchase even when Pluggy assigns a new
    transaction ID after an item re-authentication.  The key does NOT include
    the account_id so duplicates across old/new accounts are still recognised.
    """
    raw = "|".join(
        [
            account_type.upper(),
            normalize_description(description),
            tx_date.isoformat(),
            f"{abs(amount):.2f}",
            str(installment_number or 0),
            str(total_installments or 0),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class SyncAlreadyRunning(Exception):
    pass


class ItemOwnershipError(ValueError):
    pass


def pluggy_client_user_id(user_id: int) -> str:
    """Stable tenant identifier sent to Pluggy for an authenticated app user."""
    return f"openfinance-user-{user_id}"


def is_sync_lock_stale(item: Item, now: Optional[datetime] = None) -> bool:
    if item.sync_started_at is None or item.sync_finished_at is not None:
        return False
    current_time = now or datetime.utcnow()
    return item.sync_started_at < current_time - timedelta(minutes=SYNC_STALE_LOCK_MINUTES)


def sync_lock_status(item: Item, now: Optional[datetime] = None) -> str:
    if item.sync_started_at is None or item.sync_finished_at is not None:
        return "idle"
    if is_sync_lock_stale(item, now=now):
        return "stale"
    return "running"


def is_sync_running(item: Item, now: Optional[datetime] = None) -> bool:
    return sync_lock_status(item, now=now) == "running"


def _truncate_error(exc: BaseException) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    return msg[:ERROR_MESSAGE_MAX_LEN]


@dataclass
class AccountSyncResult:
    fetched_transactions: int = 0
    new_transactions: int = 0
    updated_transactions: int = 0


def upsert_item(
    item_id: str,
    session: Session,
    user_id: Optional[int] = None,
    expected_client_user_id: Optional[str] = None,
) -> Item:
    item = session.get(Item, item_id)
    if item is not None and user_id is not None and item.user_id not in (None, user_id):
        raise ItemOwnershipError(f"item {item_id!r} belongs to another user")

    data = pluggy.get_item(item_id)
    remote_client_user_id = data.get("clientUserId")
    if (
        expected_client_user_id is not None
        and remote_client_user_id is not None
        and remote_client_user_id != expected_client_user_id
    ):
        raise ItemOwnershipError(f"item {item_id!r} belongs to another Pluggy user")

    now = datetime.utcnow()
    if item is None:
        item = Item(
            id=data["id"],
            user_id=user_id,
            connector_id=data["connector"]["id"],
            connector_name=data["connector"].get("name"),
            status=data["status"],
            is_active=True,
            last_seen_at=now,
            deactivated_at=None,
        )
        session.add(item)
    else:
        # Adopt the caller's ownership only when the row isn't already owned, so
        # a webhook-triggered re-sync (user_id=None) never strips ownership.
        if user_id is not None and item.user_id is None:
            item.user_id = user_id
        item.status = data["status"]
        item.connector_name = data["connector"].get("name")
        item.is_active = True
        item.last_seen_at = now
        item.deactivated_at = None
    session.commit()
    session.refresh(item)
    return item


def upsert_account(
    raw_account: Dict[str, Any],
    item_id: str,
    session: Session,
    user_id: Optional[int] = None,
) -> None:
    account = session.get(Account, raw_account["id"])
    now = datetime.utcnow()
    values = {
        "item_id": item_id,
        "name": raw_account["name"],
        "type": raw_account["type"],
        "subtype": raw_account.get("subtype"),
        "marketing_name": raw_account.get("marketingName"),
        "number": raw_account.get("number"),
        "is_active": True,
        "last_seen_at": now,
        "deactivated_at": None,
    }
    # Pluggy snapshot fields (balance, bankData.*, creditData.*). Only keys
    # with non-null values are returned, so a connector that omits a field
    # never wipes a previously-synced value.
    values.update(account_snapshot_values(raw_account))
    if account is None:
        session.add(Account(id=raw_account["id"], user_id=user_id, **values))
        return
    if user_id is not None:
        account.user_id = user_id
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
    account_type: str = "CREDIT",
    user_id: Optional[int] = None,
) -> tuple[bool, bool, date]:
    tx_date = date.fromisoformat(raw_tx["date"][:10])
    amount = Decimal(str(raw_tx["amount"]))
    raw_total = raw_tx.get("totalAmount")
    description = raw_tx.get("description") or ""
    installment_number = raw_tx.get("installmentNumber")
    total_installments = raw_tx.get("totalInstallments")
    dedupe_key = compute_dedupe_key(
        account_type,
        description,
        tx_date,
        amount,
        installment_number,
        total_installments,
    )
    values = {
        "account_id": account_id,
        "date": tx_date,
        "amount": amount,
        "description": description,
        "category": raw_tx.get("category"),
        "currency_code": raw_tx.get("currencyCode") or "BRL",
        "status": raw_tx.get("status"),
        "bill_id": raw_tx.get("billId"),
        "installment_number": installment_number,
        "total_installments": total_installments,
        "total_amount": Decimal(str(raw_total)) if raw_total is not None else None,
        "dedupe_key": dedupe_key,
    }
    values.update(classification_payload_fields(raw_tx))
    classification = classify_pluggy_payload(
        raw_tx,
        account_type=account_type,
    )
    classification_values = classification.transaction_values()
    existing = session.get(Transaction, raw_tx["id"])
    if existing is None:
        session.add(
            Transaction(id=raw_tx["id"], user_id=user_id, **values, **classification_values)
        )
        return True, False, tx_date

    changed = False
    if user_id is not None and existing.user_id != user_id:
        existing.user_id = user_id
        changed = True
    if not existing.is_user_overridden:
        values.update(classification_values)
    for field, value in values.items():
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed = True
    if changed:
        session.add(existing)
    return False, changed, tx_date


def tracked_accounts(raw_accounts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [account for account in raw_accounts if account["type"] in TRACKED_ACCOUNT_TYPES]


def get_or_create_sync_state(
    account_id: str,
    session: Session,
    user_id: Optional[int] = None,
) -> AccountSync:
    sync_state = session.get(AccountSync, account_id)
    if sync_state is not None:
        if user_id is not None and sync_state.user_id is None:
            sync_state.user_id = user_id
        return sync_state

    sync_state = AccountSync(
        account_id=account_id,
        user_id=user_id,
        last_transaction_date=last_past_transaction_date(account_id, session),
    )
    session.add(sync_state)
    return sync_state


def sync_account_transactions(
    account_id: str,
    sync_state: AccountSync,
    session: Session,
    account_type: str = "CREDIT",
    user_id: Optional[int] = None,
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
            account_type=account_type,
            user_id=user_id,
        )
        if is_new:
            result.new_transactions += 1
        if is_updated:
            result.updated_transactions += 1
        if tx_date <= date.today() and (max_past_tx_date is None or tx_date > max_past_tx_date):
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
    user_id: Optional[int] = None,
) -> AccountSyncResult:
    account_id = raw_account["id"]
    account_type = raw_account.get("type", "CREDIT")
    upsert_account(raw_account, item_id, session, user_id=user_id)
    sync_state = get_or_create_sync_state(account_id, session, user_id=user_id)
    result = sync_account_transactions(
        account_id, sync_state, session, account_type=account_type, user_id=user_id
    )
    sync_state.last_error = None
    sync_state.last_error_at = None
    session.add(sync_state)
    return result


def _record_account_failure(
    account_id: str,
    session: Session,
    error: str,
    raw_account: Optional[Dict[str, Any]] = None,
    item_id: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    # Runs after rollback, so the AccountSync row may not exist yet.
    if raw_account is not None and item_id is not None:
        upsert_account(raw_account, item_id, session, user_id=user_id)
    sync_state = session.get(AccountSync, account_id) or AccountSync(
        account_id=account_id, user_id=user_id
    )
    if user_id is not None and sync_state.user_id is None:
        sync_state.user_id = user_id
    sync_state.last_error = error
    sync_state.last_error_at = datetime.utcnow()
    session.add(sync_state)
    session.commit()


def sync_item(item_id: str, session: Session) -> Dict[str, Any]:
    # Ownership flows from the Item: every child row written during this sync is
    # attributed to the item's owner. The authenticated route stamps the owner
    # on register/upsert; webhook-triggered syncs inherit it from the stored row.
    item = session.get(Item, item_id)
    owner_id = item.user_id if item is not None else None
    _acquire_sync_lock(item_id, session)
    try:
        result = _sync_item_locked(item_id, session, user_id=owner_id)
    except BaseException as exc:
        # Releases on top-level failure (e.g., list_accounts errored before the
        # per-account loop) so the item doesn't stay locked.
        _release_sync_lock(item_id, session, error=_truncate_error(exc))
        raise
    _release_sync_lock(item_id, session)
    return result


def _deactivate_accounts(item_id: str, keep_ids: set, session: Session) -> int:
    """Mark accounts belonging to item_id that are not in keep_ids as inactive."""
    now = datetime.utcnow()
    local_accounts = session.exec(select(Account).where(Account.item_id == item_id)).all()
    count = 0
    for account in local_accounts:
        if account.id not in keep_ids and account.is_active:
            account.is_active = False
            account.deactivated_at = now
            session.add(account)
            count += 1
    if count:
        session.commit()
    return count


def reconcile_active_items(session: Session, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Compare local Items against Pluggy and deactivate any that are gone."""
    from app.services.scoping import scope_query

    remote_items = pluggy.list_items()
    remote_ids = {item["id"] for item in remote_items}
    local_items = session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
    now = datetime.utcnow()
    deactivated_items = 0
    deactivated_accounts = 0
    for item in local_items:
        if item.id not in remote_ids and item.is_active:
            item.is_active = False
            item.deactivated_at = now
            session.add(item)
            deactivated_items += 1
            accounts = session.exec(select(Account).where(Account.item_id == item.id)).all()
            for account in accounts:
                if account.is_active:
                    account.is_active = False
                    account.deactivated_at = now
                    session.add(account)
                    deactivated_accounts += 1
    session.commit()
    return {
        "active_seen": len(remote_ids),
        "deactivated_items": deactivated_items,
        "deactivated_accounts": deactivated_accounts,
    }


def _sync_item_locked(
    item_id: str,
    session: Session,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    raw_accounts = pluggy.list_accounts(item_id)
    accounts_to_sync = tracked_accounts(raw_accounts)

    new_transactions = 0
    updated_transactions = 0
    fetched_transactions = 0
    synced_accounts_by_type: Dict[str, int] = {}
    failed_accounts: List[Dict[str, str]] = []
    bills_upserted = 0
    bill_transactions_fetched = 0
    bill_transactions_new = 0
    bill_transactions_updated = 0
    snapshot_notes: List[Dict[str, Any]] = []
    for raw_account in accounts_to_sync:
        account_id = raw_account["id"]
        account_type = raw_account["type"]
        try:
            account_result = _sync_one_account(raw_account, item_id, session, user_id=user_id)
            session.commit()
        except Exception as exc:
            session.rollback()
            error = _truncate_error(exc)
            _record_account_failure(
                account_id,
                session,
                error,
                raw_account=raw_account,
                item_id=item_id,
                user_id=user_id,
            )
            failed_accounts.append({"account_id": account_id, "error": error})
            continue

        synced_accounts_by_type[account_type] = synced_accounts_by_type.get(account_type, 0) + 1
        fetched_transactions += account_result.fetched_transactions
        new_transactions += account_result.new_transactions
        updated_transactions += account_result.updated_transactions

        # ---- Pluggy snapshot: credit-card bills (CREDIT accounts only) ----
        # Best-effort: a connector that doesn't expose /bills must not fail
        # the account's transaction sync, which already committed above.
        if account_type == "CREDIT":
            try:
                bill_outcome = sync_credit_card_bills(session, account_id, user_id=user_id)
                session.commit()
            except Exception as exc:  # noqa: BLE001 — keep the item sync alive
                session.rollback()
                snapshot_notes.append(
                    {
                        "scope": "bills",
                        "account_id": account_id,
                        "error": _truncate_error(exc),
                    }
                )
            else:
                bills_upserted += bill_outcome.upserted
                if bill_outcome.skipped_reason or bill_outcome.error:
                    snapshot_notes.append(
                        {
                            "scope": "bills",
                            "account_id": account_id,
                            "skipped": bill_outcome.skipped_reason,
                            "error": bill_outcome.error,
                        }
                    )

                # ---- Fetch transactions for each synced bill by billId ----
                # Best-effort: a per-bill failure must not roll back bill rows.
                for bill_id in bill_outcome.extras.get("bill_ids", []):
                    try:
                        for raw_tx in pluggy.list_transactions(account_id, bill_id=bill_id):
                            bill_transactions_fetched += 1
                            is_new, is_updated, _ = upsert_transaction(
                                raw_tx,
                                account_id,
                                session,
                                account_type=account_type,
                                user_id=user_id,
                            )
                            if is_new:
                                bill_transactions_new += 1
                            if is_updated:
                                bill_transactions_updated += 1
                        session.commit()
                    except Exception as exc:  # noqa: BLE001
                        session.rollback()
                        snapshot_notes.append(
                            {
                                "scope": "bill_transactions",
                                "account_id": account_id,
                                "bill_id": bill_id,
                                "error": _truncate_error(exc),
                            }
                        )

    # ---- Deactivate accounts that Pluggy no longer returns for this item ----
    synced_account_ids = {raw["id"] for raw in accounts_to_sync}
    deactivated_accounts_count = _deactivate_accounts(item_id, synced_account_ids, session)

    # ---- Pluggy snapshot: investments (per item, not per account) ----
    investments_upserted = 0
    investment_transactions_upserted = 0
    try:
        inv_outcome = sync_investments(session, item_id, user_id=user_id)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        snapshot_notes.append({"scope": "investments", "error": _truncate_error(exc)})
    else:
        investments_upserted = inv_outcome.upserted
        investment_transactions_upserted = inv_outcome.extras.get("transactions_upserted", 0)
        if inv_outcome.skipped_reason or inv_outcome.error:
            snapshot_notes.append(
                {
                    "scope": "investments",
                    "skipped": inv_outcome.skipped_reason,
                    "error": inv_outcome.error,
                }
            )

    # Snapshots aggregate from the DB, so partial failures still produce
    # meaningful numbers — just for the accounts that succeeded.
    refreshed_income_months, refreshed_invoice_months, refreshed_balance_months = (
        refresh_monthly_balance_snapshots(session, user_id=user_id)
    )
    return {
        "tracked_accounts": len(accounts_to_sync),
        "credit_accounts": synced_accounts_by_type.get("CREDIT", 0),
        "bank_accounts": synced_accounts_by_type.get("BANK", 0),
        "deactivated_accounts": deactivated_accounts_count,
        "fetched_transactions": fetched_transactions,
        "new_transactions": new_transactions,
        "updated_transactions": updated_transactions,
        "bills_upserted": bills_upserted,
        "bill_transactions_fetched": bill_transactions_fetched,
        "bill_transactions_new": bill_transactions_new,
        "bill_transactions_updated": bill_transactions_updated,
        "investments_upserted": investments_upserted,
        "investment_transactions_upserted": investment_transactions_upserted,
        "refreshed_invoice_months": refreshed_invoice_months,
        "refreshed_income_months": refreshed_income_months,
        "refreshed_balance_months": refreshed_balance_months,
        "failed_accounts": failed_accounts,
        "snapshot_notes": snapshot_notes,
    }
