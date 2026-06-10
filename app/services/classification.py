from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import (
    Account,
    BankCashflowExclusionRule,
    BankIncomeExclusionRule,
    IgnoredDescriptionRule,
    Transaction,
)
from app.services.transaction_classifier import CompiledUserRule, classify_transaction


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

# Investment movements (CDB applications + rescues) are tagged as
# INVESTMENT_NOISE so they:
#   - Don't show as outflows/inflows in the Entradas e Saídas tab
#   - Are excluded from bank_inflows_total / bank_outflows_total in Planejado
# Pluggy uses "Fixed income" for CDB applications/rescues — the main use
# case here. Extend this set if other investment categories appear.
INVESTMENT_NOISE_CATEGORIES: set[str] = {"Fixed income"}
INVESTMENT_NOISE_DESCRIPTION_PATTERNS: tuple[str, ...] = ()

# 10D-B handles Pluggy transfer categories in transaction_classifier.py as a
# structural flow type. Keep this manual list empty unless we need a temporary
# compatibility exception outside the new classifier.
INTERNAL_TRANSFER_CATEGORIES: set[str] = set()
NON_INCOME_CASHFLOW_TYPES = {
    "expense",
    "transfer",
    "credit_card_payment",
    "refund",
    "investment",
    "cash_withdrawal",
    "adjustment",
    "ignored",
    "unknown",
}


class TransactionKind(str, Enum):
    CARD_PURCHASE = "card_purchase"
    INVOICE_PAYMENT = "invoice_payment"
    BANK_INCOME = "bank_income"
    BANK_OUTFLOW = "bank_outflow"
    INTERNAL_TRANSFER = "internal_transfer"
    INVESTMENT_NOISE = "investment_noise"
    IGNORED = "ignored"
    OTHER = "other"


@dataclass(frozen=True)
class TransactionClassification:
    kind: TransactionKind
    account_type: Optional[str]
    ignored: bool = False
    bank_income_excluded: bool = False
    cashflow_excluded: bool = False

    @property
    def is_card_purchase(self) -> bool:
        return self.kind == TransactionKind.CARD_PURCHASE and not self.ignored

    @property
    def is_invoice_payment(self) -> bool:
        return self.kind == TransactionKind.INVOICE_PAYMENT

    @property
    def is_real_bank_income(self) -> bool:
        # Only the Receitas ("salary") view respects bank_income_excluded.
        return self.kind == TransactionKind.BANK_INCOME and not self.bank_income_excluded

    @property
    def is_bank_cashflow(self) -> bool:
        # Cash flow is real money movement — it must NOT be filtered by
        # BankIncomeExclusionRule. A CDB rescue isn't "salary" but IS real
        # cash entering the bank, so it has to appear in this view. Only
        # BankCashflowExclusionRule (direction-aware) or hard-coded structural
        # filters (investment_noise/internal_transfer, both empty by default)
        # should affect cashflow.
        return (
            self.kind in {TransactionKind.BANK_INCOME, TransactionKind.BANK_OUTFLOW}
            and not self.cashflow_excluded
        )


class TransactionClassifier:
    def __init__(
        self,
        accounts_by_id: dict[str, Account],
        ignored_patterns: list[str],
        bank_income_rules: list[BankIncomeExclusionRule],
        bank_cashflow_rules: list[BankCashflowExclusionRule],
        user_rules: tuple[CompiledUserRule, ...] = (),
    ):
        self.accounts_by_id = accounts_by_id
        self.ignored_patterns = ignored_patterns
        self.bank_income_rules = bank_income_rules
        self.bank_cashflow_rules = bank_cashflow_rules
        # 10D-D: user rules influence the on-the-fly cashflow type used for
        # structural decisions on transactions without persisted fields.
        self.user_rules = user_rules

    @classmethod
    def from_session(cls, session: Session) -> "TransactionClassifier":
        from app.services.user_classification_rules import load_compiled_user_rules

        accounts_by_id = {account.id: account for account in session.exec(select(Account)).all()}
        ignored_patterns = [
            rule.pattern_normalized
            for rule in session.exec(select(IgnoredDescriptionRule)).all()
            if rule.pattern_normalized
        ]
        bank_income_rules = session.exec(select(BankIncomeExclusionRule)).all()
        bank_cashflow_rules = session.exec(select(BankCashflowExclusionRule)).all()
        user_rules = load_compiled_user_rules(session)
        return cls(
            accounts_by_id=accounts_by_id,
            ignored_patterns=ignored_patterns,
            bank_income_rules=bank_income_rules,
            bank_cashflow_rules=bank_cashflow_rules,
            user_rules=user_rules,
        )

    def classify(self, tx: Transaction) -> TransactionClassification:
        account = self.accounts_by_id.get(tx.account_id)
        account_type = account.type if account is not None else None
        ignored = self._matches_ignored_description(tx)

        if self._is_invoice_payment(tx, account_type):
            return TransactionClassification(
                kind=TransactionKind.INVOICE_PAYMENT,
                account_type=account_type,
                ignored=ignored,
            )

        if account_type == "CREDIT":
            classified_cashflow_type = _cashflow_type(tx, account_type, self.user_rules)
            classification_ignored = _ignored_from_totals(tx, account_type, self.user_rules)
            if ignored or classification_ignored:
                return TransactionClassification(
                    kind=TransactionKind.IGNORED,
                    account_type=account_type,
                    ignored=True,
                )
            if classified_cashflow_type != "expense":
                return TransactionClassification(
                    kind=TransactionKind.OTHER,
                    account_type=account_type,
                )
            if tx.amount != 0:
                return TransactionClassification(
                    kind=TransactionKind.CARD_PURCHASE,
                    account_type=account_type,
                    ignored=ignored,
                )
            if ignored:
                return TransactionClassification(
                    kind=TransactionKind.IGNORED,
                    account_type=account_type,
                    ignored=True,
                )
            return TransactionClassification(
                kind=TransactionKind.OTHER,
                account_type=account_type,
            )

        if account_type == "BANK":
            return self._classify_bank_transaction(tx, ignored, account_type)

        return TransactionClassification(
            kind=TransactionKind.IGNORED if ignored else TransactionKind.OTHER,
            account_type=account_type,
            ignored=ignored,
        )

    def is_ignored(self, tx: Transaction) -> bool:
        return self.classify(tx).ignored

    def is_card_purchase(self, tx: Transaction) -> bool:
        return self.classify(tx).is_card_purchase

    def is_invoice_payment(self, tx: Transaction) -> bool:
        return self.classify(tx).is_invoice_payment

    def is_real_bank_income(self, tx: Transaction) -> bool:
        return self.classify(tx).is_real_bank_income

    def is_bank_cashflow(self, tx: Transaction) -> bool:
        return self.classify(tx).is_bank_cashflow

    def matches_bank_income_exclusion(self, tx: Transaction) -> bool:
        return self._matches_bank_income_exclusion(tx)

    def matches_bank_cashflow_exclusion(self, tx: Transaction) -> bool:
        return self._matches_bank_cashflow_exclusion(tx)

    def _classify_bank_transaction(
        self,
        tx: Transaction,
        ignored: bool,
        account_type: Optional[str],
    ) -> TransactionClassification:
        classified_cashflow_type = _cashflow_type(tx, account_type, self.user_rules)
        bank_income_excluded = tx.amount > 0 and (
            self._matches_bank_income_exclusion(tx)
            or classified_cashflow_type in NON_INCOME_CASHFLOW_TYPES
        )
        cashflow_excluded = self._matches_bank_cashflow_exclusion(tx)
        if ignored:
            return TransactionClassification(
                kind=TransactionKind.IGNORED,
                account_type=account_type,
                ignored=True,
                bank_income_excluded=bank_income_excluded,
                cashflow_excluded=cashflow_excluded,
            )
        # Structural overrides: these kinds remove the transaction from BOTH
        # the income view AND the cash-flow view because they aren't real
        # cash movement (or aren't representative of one). Both lists are
        # empty by default — see the constants for the reasoning.
        if self._looks_like_investment_noise(tx, account_type):
            return TransactionClassification(
                kind=TransactionKind.INVESTMENT_NOISE,
                account_type=account_type,
                bank_income_excluded=tx.amount > 0,
                cashflow_excluded=True,
            )
        if self._looks_like_internal_transfer(tx, account_type):
            return TransactionClassification(
                kind=TransactionKind.INTERNAL_TRANSFER,
                account_type=account_type,
                bank_income_excluded=tx.amount > 0,
                cashflow_excluded=True,
            )
        # Everything else is a normal bank movement. The KIND reflects the
        # structural sign — that doesn't change with user rules. The two
        # exclusion flags are stamped on the result so the Receitas view
        # (via is_real_bank_income) and the Entradas e Saídas view (via
        # is_bank_cashflow) each filter independently.
        if tx.amount > 0:
            return TransactionClassification(
                kind=TransactionKind.BANK_INCOME,
                account_type=account_type,
                bank_income_excluded=bank_income_excluded,
                cashflow_excluded=cashflow_excluded,
            )
        if tx.amount < 0:
            return TransactionClassification(
                kind=TransactionKind.BANK_OUTFLOW,
                account_type=account_type,
                cashflow_excluded=cashflow_excluded,
            )
        return TransactionClassification(
            kind=TransactionKind.OTHER,
            account_type=account_type,
        )

    def _matches_ignored_description(self, tx: Transaction) -> bool:
        normalized_description = normalize_description(tx.description)
        return any(pattern in normalized_description for pattern in self.ignored_patterns)

    def _is_invoice_payment(
        self,
        tx: Transaction,
        account_type: Optional[str],
    ) -> bool:
        if _cashflow_type(tx, account_type, self.user_rules) == "credit_card_payment":
            return True
        if account_type is not None and account_type != "CREDIT":
            return False
        if tx.amount >= 0:
            return False
        if _pluggy_category(tx) in CREDIT_CARD_PAYMENT_CATEGORIES:
            return True
        normalized_description = normalize_description(tx.description)
        return any(
            pattern in normalized_description
            for pattern in CREDIT_CARD_PAYMENT_DESCRIPTION_PATTERNS
            if pattern
        )

    def _matches_bank_income_exclusion(self, tx: Transaction) -> bool:
        normalized_description = normalize_description(tx.description)
        for rule in self.bank_income_rules:
            if rule.pluggy_category and _pluggy_category(tx) == rule.pluggy_category:
                return True
            if rule.pattern_normalized and rule.pattern_normalized in normalized_description:
                return True
        return False

    def _matches_bank_cashflow_exclusion(self, tx: Transaction) -> bool:
        normalized_description = normalize_description(tx.description)
        for rule in self.bank_cashflow_rules:
            if not self._cashflow_rule_matches_direction(tx, rule):
                continue
            if rule.pluggy_category and _pluggy_category(tx) == rule.pluggy_category:
                return True
            if rule.pattern_normalized and rule.pattern_normalized in normalized_description:
                return True
        return False

    @staticmethod
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

    def _looks_like_investment_noise(
        self,
        tx: Transaction,
        account_type: Optional[str] = None,
    ) -> bool:
        if _cashflow_type(tx, account_type, self.user_rules) == "investment":
            return True
        if _pluggy_category(tx) in INVESTMENT_NOISE_CATEGORIES:
            return True
        normalized_description = normalize_description(tx.description)
        return any(
            pattern in normalized_description
            for pattern in INVESTMENT_NOISE_DESCRIPTION_PATTERNS
            if pattern
        )

    def _looks_like_internal_transfer(
        self,
        tx: Transaction,
        account_type: Optional[str] = None,
    ) -> bool:
        if _cashflow_type(tx, account_type, self.user_rules) == "transfer":
            return True
        return _pluggy_category(tx) in INTERNAL_TRANSFER_CATEGORIES


def _pluggy_category(tx: Transaction) -> Optional[str]:
    return tx.pluggy_raw_category or tx.category


def _cashflow_type(
    tx: Transaction,
    account_type: Optional[str] = None,
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> Optional[str]:
    if tx.cashflow_type:
        return tx.cashflow_type
    return classify_transaction(
        tx,
        account_type=account_type,
        user_rules=user_rules,
    ).cashflow_type


def _ignored_from_totals(
    tx: Transaction,
    account_type: Optional[str] = None,
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> bool:
    if tx.internal_category and tx.cashflow_type and tx.classification_source:
        return bool(tx.ignored_from_totals)
    return classify_transaction(
        tx,
        account_type=account_type,
        user_rules=user_rules,
    ).ignored_from_totals
