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
from app.services.classification import (
    BANK_ACCOUNT_TYPES,
    SPENDING_ACCOUNT_TYPES,
    TRACKED_ACCOUNT_TYPES,
    TransactionClassifier,
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
    classifier = TransactionClassifier.from_session(session)
    return [tx for tx in transactions if not classifier.is_ignored(tx)]


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
    classifier = TransactionClassifier(
        accounts_by_id=accounts_by_id,
        ignored_patterns=[],
        bank_income_rules=[],
        bank_cashflow_rules=[],
    )
    return classifier.is_invoice_payment(tx)


def credit_card_payment_transactions(
    session: Session,
    start_date: date,
    end_date: date,
) -> list[Transaction]:
    classifier = TransactionClassifier.from_session(session)
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.date >= start_date, Transaction.date <= end_date)
        .order_by(Transaction.date.asc())
    ).all()
    return [tx for tx in transactions if classifier.is_invoice_payment(tx)]


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
    classifier = TransactionClassifier(
        accounts_by_id={},
        ignored_patterns=[],
        bank_income_rules=[],
        bank_cashflow_rules=rules,
    )
    return classifier.matches_bank_cashflow_exclusion(tx)


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
    classifier = TransactionClassifier(
        accounts_by_id={},
        ignored_patterns=[],
        bank_income_rules=rules,
        bank_cashflow_rules=[],
    )
    return classifier.matches_bank_income_exclusion(tx)


def filter_real_bank_income_transactions(
    transactions: list[Transaction],
    session: Session,
) -> list[Transaction]:
    classifier = TransactionClassifier.from_session(session)
    return [tx for tx in transactions if classifier.is_real_bank_income(tx)]


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
    if include_ignored:
        return transactions
    classifier = TransactionClassifier.from_session(session)
    return [tx for tx in transactions if classifier.is_card_purchase(tx)]


def discretionary_spend_transactions(
    session: Session,
    start_date: date,
    end_date: date,
    include_ignored: bool = False,
) -> list[Transaction]:
    """Return transactions that count as personal discretionary spending.

    Includes:
      - CREDIT purchases (non-invoice-payment, non-ignored)
      - BANK outflows that pass cashflow filters (non-internal-transfer,
        non-investment-noise, non-cashflow-excluded, non-ignored)

    Used by ``budget_progress_summary`` so PIX/débito leaving the bank
    account is visible to the budget — historically only credit-card
    spending was counted, which under-reported real expenses in Brazil.
    """
    from app.services.classification import TransactionKind

    classifier = TransactionClassifier.from_session(session)
    tracked_account_ids = set(
        account_ids_by_type(session, TRACKED_ACCOUNT_TYPES)
    )
    if not tracked_account_ids:
        return []
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(tracked_account_ids),
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        .order_by(Transaction.date.asc())
    ).all()
    out: list[Transaction] = []
    for tx in rows:
        classification = classifier.classify(tx)
        if classification.ignored and not include_ignored:
            continue
        kind = classification.kind
        if kind == TransactionKind.CARD_PURCHASE:
            out.append(tx)
            continue
        # BANK side: only outflows count as spending, and only when they
        # survive the cashflow filters (so we drop internal transfers and
        # investment movements).
        if (
            kind == TransactionKind.BANK_OUTFLOW
            and not classification.cashflow_excluded
        ):
            out.append(tx)
    return out


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
