from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, select

from app.models import Account, Item
from app.services.scoping import scope_query


def bank_balance_summary(session: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    """Return total balance across all active BANK accounts.

    Rules:
    - Account.type == "BANK"
    - Account.is_active == True
    - Account.item_id belongs to an active Item
    - Accounts with balance=None are treated as zero (no balance data yet)
    """
    active_item_ids = {
        item.id
        for item in session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
        if item.is_active
    }
    accounts = [
        a
        for a in session.exec(scope_query(select(Account), Account.user_id, user_id)).all()
        if a.type == "BANK" and a.is_active and a.item_id in active_item_ids
    ]

    total = sum(
        (Decimal(str(a.balance)) for a in accounts if a.balance is not None),
        Decimal("0"),
    )

    updated_ats = [a.balance_updated_at for a in accounts if a.balance_updated_at]
    updated_at: str | None = max(updated_ats).isoformat() if updated_ats else None

    return {
        "total": float(total),
        "account_count": len(accounts),
        "updated_at": updated_at,
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "balance": float(a.balance) if a.balance is not None else None,
                "balance_updated_at": (
                    a.balance_updated_at.isoformat() if a.balance_updated_at else None
                ),
            }
            for a in accounts
        ],
        "source": "active_bank_accounts",
    }
