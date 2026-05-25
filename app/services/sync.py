from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import Account, AccountSync, Item, Transaction
from app.pluggy_client import pluggy
from app.services.snapshots import refresh_monthly_balance_snapshots
from app.services.transactions import TRACKED_ACCOUNT_TYPES

SYNC_LOOKBACK_DAYS = 7


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


def sync_item(item_id: str, session: Session) -> Dict[str, int]:
    raw_accounts = pluggy.list_accounts(item_id)
    tracked_accounts = [
        a for a in raw_accounts if a["type"] in TRACKED_ACCOUNT_TYPES
    ]

    new_transactions = 0
    updated_transactions = 0
    fetched_transactions = 0
    synced_accounts_by_type: Dict[str, int] = {}
    for raw_account in tracked_accounts:
        account_id = raw_account["id"]
        account_type = raw_account["type"]
        synced_accounts_by_type[account_type] = (
            synced_accounts_by_type.get(account_type, 0) + 1
        )
        upsert_account(raw_account, item_id, session)

        sync_state = session.get(AccountSync, account_id)
        if sync_state is None:
            sync_state = AccountSync(
                account_id=account_id,
                last_transaction_date=last_past_transaction_date(account_id, session),
            )
            session.add(sync_state)

        max_past_tx_date = sync_state.last_transaction_date
        for raw_tx in pluggy.list_transactions(
            account_id,
            from_date=sync_from_date(sync_state),
        ):
            fetched_transactions += 1
            is_new, is_updated, tx_date = upsert_transaction(
                raw_tx,
                account_id,
                session,
            )
            if is_new:
                new_transactions += 1
            if is_updated:
                updated_transactions += 1
            if tx_date <= date.today() and (
                max_past_tx_date is None or tx_date > max_past_tx_date
            ):
                max_past_tx_date = tx_date

        sync_state.last_transaction_date = max_past_tx_date
        sync_state.last_synced_at = datetime.utcnow()
        session.add(sync_state)

    session.commit()
    # refresh_monthly_balance_snapshots internally refreshes income and invoice
    # snapshots first, so a single call is enough — no double work.
    refreshed_income_months, refreshed_invoice_months, refreshed_balance_months = (
        refresh_monthly_balance_snapshots(session)
    )
    return {
        "tracked_accounts": len(tracked_accounts),
        "credit_accounts": synced_accounts_by_type.get("CREDIT", 0),
        "bank_accounts": synced_accounts_by_type.get("BANK", 0),
        "fetched_transactions": fetched_transactions,
        "new_transactions": new_transactions,
        "updated_transactions": updated_transactions,
        "refreshed_invoice_months": refreshed_invoice_months,
        "refreshed_income_months": refreshed_income_months,
        "refreshed_balance_months": refreshed_balance_months,
    }
