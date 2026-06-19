import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.dependencies import current_scope_user_id
from app.config import database_settings, get_pluggy_settings
from app.database import get_session
from app.models import Account, AccountSync, Item, Transaction
from app.pluggy_client import PluggyCredentialError, pluggy
from app.services.database_backup import backup_sqlite_database
from app.services.scoping import scope_query
from app.services.sync import (
    SyncAlreadyRunning,
    compute_dedupe_key,
    is_sync_running,
    reconcile_active_items,
    sync_item as run_sync_item,
    sync_lock_status,
    upsert_item,
)
from app.services.sync_status import get_sync_status

logger = logging.getLogger("openfinance")

router = APIRouter()


class ConnectTokenRequest(BaseModel):
    clientUserId: Optional[str] = None
    itemId: Optional[str] = None


@router.post("/connect-token")
def connect_token(body: Optional[ConnectTokenRequest] = None):
    body = body or ConnectTokenRequest()
    # Log enough to diagnose credential/environment problems without leaking secrets.
    settings = get_pluggy_settings()
    _masked_id = (settings.pluggy_client_id[:4] + "…") if settings.pluggy_client_id else "<not set>"
    logger.info(
        "connect-token request base_url=%s client_id=%s item_id=%s",
        settings.pluggy_base_url,
        _masked_id,
        body.itemId,
    )
    try:
        token = pluggy.create_connect_token(client_user_id=body.clientUserId, item_id=body.itemId)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "connect-token Pluggy error status=%s body=%.500s",
            exc.response.status_code,
            exc.response.text,
        )
        if exc.response.status_code in (401, 403):
            raise HTTPException(
                401,
                "Pluggy rejeitou as credenciais. Verifique PLUGGY_CLIENT_ID e "
                "PLUGGY_CLIENT_SECRET no arquivo .env.",
            )
        raise HTTPException(502, f"Pluggy retornou {exc.response.status_code}: {exc.response.text}")
    except PluggyCredentialError as exc:
        raise HTTPException(
            500,
            "Configure PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no arquivo .env "
            "antes de conectar ao Pluggy.",
        ) from exc
    except Exception as exc:
        logger.exception("connect-token unexpected error: %s", exc)
        raise HTTPException(500, f"Erro interno ao gerar token de conexão: {exc}") from exc
    logger.info("connect-token issued successfully")
    return {"accessToken": token}


@router.post("/items/{item_id}")
def register_item(
    item_id: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return upsert_item(item_id, session, user_id=user_id)


@router.post("/items/{item_id}/sync")
def sync_item(
    item_id: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        backup_sqlite_database(database_settings.database_url, f"pluggy-sync-{item_id}")
    except Exception as exc:
        logger.error(
            "SQLite backup before Pluggy sync failed for item_id=%s error=%s",
            item_id,
            type(exc).__name__,
        )
        raise HTTPException(
            500,
            "Could not create SQLite backup before starting Pluggy sync.",
        ) from exc

    item = session.get(Item, item_id)
    if item is not None and user_id is not None and item.user_id != user_id:
        raise HTTPException(404, f"Item {item_id!r} not found")
    if item is None:
        item = upsert_item(item_id, session, user_id=user_id)
    try:
        return run_sync_item(item.id, session)
    except SyncAlreadyRunning:
        raise HTTPException(409, "sync already running for this item")


@router.get("/items")
def list_items(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return session.exec(scope_query(select(Item), Item.user_id, user_id)).all()


@router.get("/sync/health")
def sync_health(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    items = session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
    accounts_by_id = {
        account.id: account
        for account in session.exec(scope_query(select(Account), Account.user_id, user_id)).all()
    }
    failed_syncs = session.exec(
        scope_query(
            select(AccountSync).where(AccountSync.last_error.is_not(None)),
            AccountSync.user_id,
            user_id,
        )
    ).all()
    health = []
    for item in items:
        lock_status = sync_lock_status(item)
        failed = [
            sync
            for sync in failed_syncs
            if accounts_by_id.get(sync.account_id)
            and accounts_by_id[sync.account_id].item_id == item.id
        ]
        health.append(
            {
                "item_id": item.id,
                "connector_name": item.connector_name,
                "status": item.status,
                "is_active": item.is_active,
                "deactivated_at": item.deactivated_at,
                "sync_started_at": item.sync_started_at,
                "sync_finished_at": item.sync_finished_at,
                "is_running": is_sync_running(item),
                "sync_lock_status": lock_status,
                "last_sync_error": item.last_sync_error,
                "failed_accounts": [
                    {
                        "account_id": sync.account_id,
                        "account_name": accounts_by_id[sync.account_id].name,
                        "account_type": accounts_by_id[sync.account_id].type,
                        "error": sync.last_error,
                        "last_error_at": sync.last_error_at,
                    }
                    for sync in failed
                ],
            }
        )
    return health


@router.get("/sync/status")
def sync_status(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return get_sync_status(session, user_id=user_id)


@router.post("/sync/items/{item_id}/deactivate")
def deactivate_item(
    item_id: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    item = session.get(Item, item_id)
    if item is None or (user_id is not None and item.user_id != user_id):
        raise HTTPException(404, f"Item {item_id!r} not found")
    now = datetime.utcnow()
    item.is_active = False
    item.deactivated_at = now
    session.add(item)
    accounts = session.exec(
        scope_query(
            select(Account).where(Account.item_id == item_id), Account.user_id, user_id
        )
    ).all()
    for account in accounts:
        account.is_active = False
        account.deactivated_at = now
        session.add(account)
    session.commit()
    return {
        "item_id": item_id,
        "deactivated_item": True,
        "deactivated_accounts": len(accounts),
    }


@router.post("/sync/reconcile-items")
def reconcile_items(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return reconcile_active_items(session, user_id=user_id)


@router.get("/accounts")
def list_accounts(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return session.exec(scope_query(select(Account), Account.user_id, user_id)).all()


@router.get("/debug/duplicate-transactions")
def debug_duplicate_transactions(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    """Read-only diagnostic: find transactions that look like re-auth duplicates.

    Groups all transactions by their natural key (account_type + description +
    date + |amount| + installment fields).  Groups with 2+ transactions are
    candidates for deduplication.

    Returns:
      - summary: counts and totals
      - duplicate_groups: each group with active/inactive account breakdowns
      - inactive_accounts: list of deactivated accounts still holding transactions
    """
    # --- load accounts and items ---
    all_accounts: dict[str, Account] = {
        a.id: a
        for a in session.exec(scope_query(select(Account), Account.user_id, user_id)).all()
    }
    active_item_ids = {
        item.id
        for item in session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
        if item.is_active
    }

    def _is_account_active(account: Account) -> bool:
        return bool(account.is_active and account.item_id in active_item_ids)

    # --- load all transactions ---
    all_txs = session.exec(scope_query(select(Transaction), Transaction.user_id, user_id)).all()

    # --- group by natural key ---
    by_key: dict[str, list[Transaction]] = defaultdict(list)
    for tx in all_txs:
        account = all_accounts.get(tx.account_id)
        account_type = account.type if account else "UNKNOWN"
        key = tx.dedupe_key or compute_dedupe_key(
            account_type,
            tx.description,
            tx.date,
            tx.amount,
            tx.installment_number,
            tx.total_installments,
        )
        by_key[key].append(tx)

    # --- identify duplicate groups ---
    duplicate_groups = []
    total_duplicate_txs = 0
    confirmed_duplicate_amount = 0.0

    for key, txs in by_key.items():
        if len(txs) < 2:
            continue
        active_txs = [tx for tx in txs if _is_account_active(all_accounts.get(tx.account_id))]
        inactive_txs = [tx for tx in txs if not _is_account_active(all_accounts.get(tx.account_id))]
        total_duplicate_txs += len(inactive_txs)
        confirmed_duplicate_amount += sum(abs(float(tx.amount)) for tx in inactive_txs)
        duplicate_groups.append(
            {
                "dedupe_key": key,
                "total_in_group": len(txs),
                "active_count": len(active_txs),
                "inactive_count": len(inactive_txs),
                "active_transactions": [
                    {
                        "id": tx.id,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "description": tx.description,
                        "account_id": tx.account_id,
                        "is_duplicate": tx.is_duplicate,
                    }
                    for tx in active_txs
                ],
                "inactive_transactions": [
                    {
                        "id": tx.id,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "description": tx.description,
                        "account_id": tx.account_id,
                        "is_duplicate": tx.is_duplicate,
                    }
                    for tx in inactive_txs
                ],
            }
        )

    # Sort by inactive_count desc so worst offenders appear first
    duplicate_groups.sort(key=lambda g: g["inactive_count"], reverse=True)

    # --- inactive accounts still holding transactions ---
    tx_count_by_account: dict[str, int] = defaultdict(int)
    for tx in all_txs:
        tx_count_by_account[tx.account_id] += 1

    inactive_accounts = [
        {
            "account_id": a.id,
            "item_id": a.item_id,
            "name": a.name,
            "type": a.type,
            "is_active": a.is_active,
            "item_active": a.item_id in active_item_ids,
            "deactivated_at": a.deactivated_at.isoformat() if a.deactivated_at else None,
            "transaction_count": tx_count_by_account.get(a.id, 0),
        }
        for a in all_accounts.values()
        if not _is_account_active(a) and tx_count_by_account.get(a.id, 0) > 0
    ]

    already_marked = sum(1 for tx in all_txs if tx.is_duplicate)
    return {
        "summary": {
            "total_transactions": len(all_txs),
            "already_marked_duplicate": already_marked,
            "duplicate_groups_found": len(duplicate_groups),
            "transactions_in_duplicate_groups": sum(g["total_in_group"] for g in duplicate_groups),
            "inactive_duplicates_found": total_duplicate_txs,
            "inactive_duplicate_amount": round(confirmed_duplicate_amount, 2),
        },
        "inactive_accounts_with_transactions": inactive_accounts,
        "duplicate_groups": duplicate_groups,
    }
