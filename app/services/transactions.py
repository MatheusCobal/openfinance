from datetime import date

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import (
    Account,
    BankCashflowExclusionRule,
    BankIncomeExclusionRule,
    IgnoredDescriptionRule,
    Transaction,
)

TRACKED_ACCOUNT_TYPES = {"CREDIT", "BANK"}
SPENDING_ACCOUNT_TYPES = {"CREDIT"}
BANK_ACCOUNT_TYPES = {"BANK"}
CREDIT_CARD_PAYMENT_CATEGORIES = {"Credit card payment", "Card payments"}
CREDIT_CARD_PAYMENT_DESCRIPTION_PATTERNS = tuple(
    normalize_description(pattern)
    for pattern in (
        "PAGAMENTO COM SALDO",
        "Pagamento recebido",
    )
)


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def shift_month(value: date, months: int) -> date:
    zero_based_month = value.year * 12 + value.month - 1 + months
    year = zero_based_month // 12
    month = zero_based_month % 12 + 1
    return date(year, month, 1)


def last_month_keys(count: int, today: date) -> list[str]:
    current_month = date(today.year, today.month, 1)
    return [
        month_key(shift_month(current_month, offset))
        for offset in range(-(count - 1), 1)
    ]


def ignored_description_patterns(session: Session) -> list[str]:
    return [
        rule.pattern_normalized
        for rule in session.exec(select(IgnoredDescriptionRule)).all()
        if rule.pattern_normalized
    ]


def is_ignored_transaction(tx: Transaction, patterns: list[str]) -> bool:
    normalized_description = normalize_description(tx.description)
    return any(pattern in normalized_description for pattern in patterns)


def filter_ignored_transactions(
    transactions: list[Transaction],
    session: Session,
    include_ignored: bool,
) -> list[Transaction]:
    if include_ignored:
        return transactions
    patterns = ignored_description_patterns(session)
    if not patterns:
        return transactions
    return [tx for tx in transactions if not is_ignored_transaction(tx, patterns)]


def account_ids_by_type(session: Session, account_types: set[str]) -> list[str]:
    return [
        account.id
        for account in session.exec(select(Account)).all()
        if account.type in account_types
    ]


def filter_transactions_by_account_type(
    transactions: list[Transaction],
    session: Session,
    account_types: set[str],
) -> list[Transaction]:
    account_ids = set(account_ids_by_type(session, account_types))
    if not account_ids:
        return []
    return [tx for tx in transactions if tx.account_id in account_ids]


def is_credit_card_payment_transaction(
    tx: Transaction,
    accounts_by_id: dict[str, Account],
) -> bool:
    account = accounts_by_id.get(tx.account_id)
    if account is not None and account.type != "CREDIT":
        return False
    if tx.amount >= 0:
        return False
    if tx.category in CREDIT_CARD_PAYMENT_CATEGORIES:
        return True
    normalized_description = normalize_description(tx.description)
    return any(
        pattern in normalized_description
        for pattern in CREDIT_CARD_PAYMENT_DESCRIPTION_PATTERNS
        if pattern
    )


def credit_card_payment_transactions(
    session: Session,
    start_date: date,
    end_date: date,
) -> list[Transaction]:
    accounts_by_id = {
        account.id: account for account in session.exec(select(Account)).all()
    }
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.date >= start_date, Transaction.date <= end_date)
        .order_by(Transaction.date.asc())
    ).all()
    return [
        tx
        for tx in transactions
        if is_credit_card_payment_transaction(tx, accounts_by_id)
    ]


def bank_income_exclusion_rules(
    session: Session,
) -> list[BankIncomeExclusionRule]:
    return session.exec(select(BankIncomeExclusionRule)).all()


def bank_cashflow_exclusion_rules(
    session: Session,
) -> list[BankCashflowExclusionRule]:
    return session.exec(select(BankCashflowExclusionRule)).all()


def _cashflow_rule_matches_direction(
    tx: Transaction,
    rule: BankCashflowExclusionRule,
) -> bool:
    direction = (rule.direction or "ALL").upper()
    if direction == "IN":
        return tx.amount > 0
    if direction == "OUT":
        return tx.amount < 0
    return True


def is_excluded_bank_cashflow_transaction(
    tx: Transaction,
    rules: list[BankCashflowExclusionRule],
) -> bool:
    normalized_description = normalize_description(tx.description)
    for rule in rules:
        if not _cashflow_rule_matches_direction(tx, rule):
            continue
        if rule.pluggy_category and tx.category == rule.pluggy_category:
            return True
        if (
            rule.pattern_normalized
            and rule.pattern_normalized in normalized_description
        ):
            return True
    return False


def count_bank_cashflow_exclusion_matches(
    rule: BankCashflowExclusionRule,
    session: Session,
) -> int:
    transactions = filter_transactions_by_account_type(
        session.exec(select(Transaction)).all(),
        session,
        BANK_ACCOUNT_TYPES,
    )
    return sum(
        1
        for tx in transactions
        if is_excluded_bank_cashflow_transaction(tx, [rule])
    )


def is_excluded_bank_income_transaction(
    tx: Transaction,
    rules: list[BankIncomeExclusionRule],
) -> bool:
    normalized_description = normalize_description(tx.description)
    for rule in rules:
        if rule.pluggy_category and tx.category == rule.pluggy_category:
            return True
        if (
            rule.pattern_normalized
            and rule.pattern_normalized in normalized_description
        ):
            return True
    return False


def filter_real_bank_income_transactions(
    transactions: list[Transaction],
    session: Session,
) -> list[Transaction]:
    rules = bank_income_exclusion_rules(session)
    return [
        tx
        for tx in transactions
        if tx.amount > 0 and not is_excluded_bank_income_transaction(tx, rules)
    ]


def bank_income_transactions(
    session: Session,
    start_date: date,
    end_date: date,
) -> list[Transaction]:
    bank_account_ids = account_ids_by_type(session, BANK_ACCOUNT_TYPES)
    if not bank_account_ids:
        return []
    transactions = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(bank_account_ids),
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        .order_by(Transaction.date.asc())
    ).all()
    return filter_real_bank_income_transactions(transactions, session)


def credit_card_spend_transactions(
    session: Session,
    start_date: date,
    end_date: date,
    include_ignored: bool = False,
) -> list[Transaction]:
    credit_account_ids = account_ids_by_type(session, SPENDING_ACCOUNT_TYPES)
    if not credit_account_ids:
        return []
    transactions = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(credit_account_ids),
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        .order_by(Transaction.date.asc())
    ).all()
    return filter_ignored_transactions(transactions, session, include_ignored)


def count_bank_income_exclusion_matches(
    rule: BankIncomeExclusionRule,
    session: Session,
) -> int:
    bank_account_ids = account_ids_by_type(session, BANK_ACCOUNT_TYPES)
    if not bank_account_ids:
        return 0
    transactions = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(bank_account_ids),
            Transaction.amount > 0,
        )
    ).all()
    return sum(
        1
        for tx in transactions
        if is_excluded_bank_income_transaction(tx, [rule])
    )
