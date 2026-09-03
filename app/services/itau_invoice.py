from typing import Optional

from app.categorization import normalize_description
from app.models import Account, Transaction


def is_itau_account(account: Optional[Account]) -> bool:
    if account is None or account.type != "CREDIT":
        return False
    identity = normalize_description(f"{account.marketing_name or ''} {account.name or ''}")
    return "itau" in identity.split() and "caixa" not in identity.split()


def is_unconfirmed_itau_transaction(tx: Transaction, account: Optional[Account]) -> bool:
    """Only the provider's POSTED status confirms an Itaú transaction."""
    return is_itau_account(account) and str(tx.status or "").upper() != "POSTED"
