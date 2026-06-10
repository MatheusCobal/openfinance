from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from app.categorization import normalize_description
from app.models import Transaction


CASHFLOW_TYPES = {
    "expense",
    "income",
    "transfer",
    "credit_card_payment",
    "refund",
    "investment",
    "cash_withdrawal",
    "adjustment",
    "ignored",
    "unknown",
}
CLASSIFICATION_SOURCES = {
    "pluggy_rule",
    "system_rule",
    "manual_override",
    "fallback",
    "unclassified",
}
CLASSIFICATION_CONFIDENCES = {"high", "medium", "low", "unknown"}

INTERNAL_CATEGORIES = (
    "Alimentação",
    "Transporte",
    "Moradia",
    "Saúde",
    "Compras",
    "Assinaturas",
    "Educação",
    "Pet",
    "Lazer",
    "Viagem",
    "Presentes",
    "Beleza / Cuidados pessoais",
    "Impostos / Taxas",
    "Financiamentos",
    "Receitas",
    "Transferências",
    "Pagamento de cartão",
    "Investimentos",
    "Saque",
    "Estorno",
    "Ajustes",
    "Ignorar",
    "Outros",
)

IGNORED_CASHFLOW_TYPES = {
    "transfer",
    "credit_card_payment",
    "investment",
    "cash_withdrawal",
    "adjustment",
    "ignored",
}


@dataclass(frozen=True)
class ClassificationInput:
    pluggy_raw_category: Optional[str] = None
    pluggy_raw_subcategory: Optional[str] = None
    pluggy_raw_type: Optional[str] = None
    pluggy_merchant: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    account_type: Optional[str] = None
    is_user_overridden: bool = False


@dataclass(frozen=True)
class ClassificationResult:
    internal_category: str
    cashflow_type: str
    source: str
    confidence: str
    matched_rule: str
    ignored_from_totals: bool = False

    def transaction_values(self) -> dict[str, Any]:
        return {
            "internal_category": self.internal_category,
            "cashflow_type": self.cashflow_type,
            "classification_source": self.source,
            "classification_confidence": self.confidence,
            "classification_rule_key": self.matched_rule,
            "ignored_from_totals": self.ignored_from_totals,
        }


@dataclass(frozen=True)
class _Rule:
    internal_category: str
    cashflow_type: str
    confidence: str = "high"
    ignored_from_totals: Optional[bool] = None


_CATEGORY_RULES: dict[str, _Rule] = {
    "food": _Rule("Alimentação", "expense"),
    "food delivery": _Rule("Alimentação", "expense"),
    "food and drinks": _Rule("Alimentação", "expense"),
    "delivery": _Rule("Alimentação", "expense"),
    "restaurant": _Rule("Alimentação", "expense"),
    "restaurants": _Rule("Alimentação", "expense"),
    "eating out": _Rule("Alimentação", "expense"),
    "market": _Rule("Alimentação", "expense"),
    "grocery": _Rule("Alimentação", "expense"),
    "groceries": _Rule("Alimentação", "expense"),
    "transport": _Rule("Transporte", "expense"),
    "transportation": _Rule("Transporte", "expense"),
    "taxi and ride hailing": _Rule("Transporte", "expense"),
    "ride app": _Rule("Transporte", "expense"),
    "ride_app": _Rule("Transporte", "expense"),
    "fuel": _Rule("Transporte", "expense"),
    "gas station": _Rule("Transporte", "expense"),
    "gas stations": _Rule("Transporte", "expense"),
    "parking": _Rule("Transporte", "expense"),
    "automotive": _Rule("Transporte", "expense"),
    "vehicle maintenance": _Rule("Transporte", "expense"),
    "tolls and in vehicle payment": _Rule("Transporte", "expense"),
    "health": _Rule("Saúde", "expense"),
    "healthcare": _Rule("Saúde", "expense"),
    "pharmacy": _Rule("Saúde", "expense"),
    "drugstore": _Rule("Saúde", "expense"),
    "medical": _Rule("Saúde", "expense"),
    "hospital clinics and labs": _Rule("Saúde", "expense"),
    "dentist": _Rule("Saúde", "expense"),
    "shopping": _Rule("Compras", "expense"),
    "online shopping": _Rule("Compras", "expense"),
    "electronics": _Rule("Compras", "expense"),
    "houseware": _Rule("Compras", "expense"),
    "clothing": _Rule("Compras", "expense"),
    "office supplies": _Rule("Compras", "expense"),
    "sports goods": _Rule("Compras", "expense"),
    "bookstore": _Rule("Educação", "expense"),
    "school": _Rule("Educação", "expense"),
    "education": _Rule("Educação", "expense"),
    "online courses": _Rule("Educação", "expense"),
    "pet": _Rule("Pet", "expense"),
    "pet supplies and vet": _Rule("Pet", "expense"),
    "digital services": _Rule("Assinaturas", "expense"),
    "telecommunications": _Rule("Assinaturas", "expense"),
    "services": _Rule("Assinaturas", "expense"),
    "internet": _Rule("Assinaturas", "expense"),
    "mobile": _Rule("Assinaturas", "expense"),
    "wellness and fitness": _Rule("Beleza / Cuidados pessoais", "expense"),
    "wellness": _Rule("Beleza / Cuidados pessoais", "expense"),
    "gyms and fitness centers": _Rule("Beleza / Cuidados pessoais", "expense"),
    "beauty": _Rule("Beleza / Cuidados pessoais", "expense"),
    "personal care": _Rule("Beleza / Cuidados pessoais", "expense"),
    "cinema theater and concerts": _Rule("Lazer", "expense"),
    "gaming": _Rule("Lazer", "expense"),
    "stadiums and arenas": _Rule("Lazer", "expense"),
    "tickets": _Rule("Lazer", "expense"),
    "leisure": _Rule("Lazer", "expense"),
    "mileage programs": _Rule("Viagem", "expense"),
    "airport and airlines": _Rule("Viagem", "expense"),
    "accomodation": _Rule("Viagem", "expense"),
    "accommodation": _Rule("Viagem", "expense"),
    "kids and toys": _Rule("Presentes", "expense"),
    "donations": _Rule("Presentes", "expense"),
    "electricity": _Rule("Moradia", "expense"),
    "water": _Rule("Moradia", "expense"),
    "housing": _Rule("Moradia", "expense"),
    "rent": _Rule("Moradia", "expense"),
    "real estate financing": _Rule("Financiamentos", "expense"),
    "tax": _Rule("Impostos / Taxas", "expense"),
    "taxes": _Rule("Impostos / Taxas", "expense"),
    "income taxes": _Rule("Impostos / Taxas", "expense"),
    "vehicle ownership taxes and fees": _Rule("Impostos / Taxas", "expense"),
    "fee": _Rule("Impostos / Taxas", "expense"),
    "fees": _Rule("Impostos / Taxas", "expense"),
    "credit card fees": _Rule("Impostos / Taxas", "expense"),
    "tax on financial operations": _Rule("Impostos / Taxas", "expense"),
    "income": _Rule("Receitas", "income"),
    "salary": _Rule("Receitas", "income"),
    "paycheck": _Rule("Receitas", "income"),
    "proceeds interests and dividends": _Rule("Receitas", "income"),
    "transfer": _Rule("Transferências", "transfer"),
    "transfers": _Rule("Transferências", "transfer"),
    "transfer pix": _Rule("Transferências", "transfer"),
    "transfer ted": _Rule("Transferências", "transfer"),
    "same person transfer": _Rule("Transferências", "transfer"),
    "internal transfer": _Rule("Transferências", "transfer"),
    "internal_transfer": _Rule("Transferências", "transfer"),
    # "Transfer - Internal" / "Transfer - Bank Slip" normalize with the
    # qualifier after the word "transfer"; without these keys they fell
    # through to the BANK positive-amount fallback and counted as income.
    "transfer internal": _Rule("Transferências", "transfer"),
    "transfer bank slip": _Rule("Transferências", "transfer"),
    "credit card payment": _Rule("Pagamento de cartão", "credit_card_payment"),
    "card payment": _Rule("Pagamento de cartão", "credit_card_payment"),
    "card payments": _Rule("Pagamento de cartão", "credit_card_payment"),
    "credit_card_payment": _Rule("Pagamento de cartão", "credit_card_payment"),
    "investment": _Rule("Investimentos", "investment"),
    "investments": _Rule("Investimentos", "investment"),
    "fixed income": _Rule("Investimentos", "investment"),
    "brokerage": _Rule("Investimentos", "investment"),
    "automatic investment": _Rule("Investimentos", "investment"),
    "refund": _Rule("Estorno", "refund"),
    "chargeback": _Rule("Estorno", "refund"),
    "cash withdrawal": _Rule("Saque", "cash_withdrawal"),
    "cash_withdrawal": _Rule("Saque", "cash_withdrawal"),
    "atm": _Rule("Saque", "cash_withdrawal"),
    "adjustment": _Rule("Ajustes", "adjustment"),
}


_TYPE_RULES: dict[str, _Rule] = {
    "income": _Rule("Receitas", "income"),
    "debit": _Rule("Outros", "expense", confidence="medium"),
    "credit": _Rule("Receitas", "income", confidence="medium"),
    "transfer": _Rule("Transferências", "transfer"),
    "credit_card_payment": _Rule("Pagamento de cartão", "credit_card_payment"),
    "refund": _Rule("Estorno", "refund"),
    "investment": _Rule("Investimentos", "investment"),
}


_REFUND_PATTERNS = tuple(
    normalize_description(value)
    for value in (
        "refund",
        "reembolso",
        "estorno",
        "chargeback",
        "cancelamento",
        "cancelada",
    )
)
_INVOICE_PAYMENT_PATTERNS = tuple(
    normalize_description(value)
    for value in (
        "pagamento recebido",
        "pagamento com saldo",
        "credit card payment",
    )
)


def normalize_pluggy_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for token in ("_", "-", ",", "/", "&"):
        text = text.replace(token, " ")
    normalized = normalize_description(text)
    return normalized or None


def classify_input(data: ClassificationInput) -> ClassificationResult:
    if data.is_user_overridden:
        # 10D-B does not create manual overrides. Preserve the source contract
        # for a future caller without inventing category values.
        return ClassificationResult(
            internal_category="Outros",
            cashflow_type="unknown",
            source="manual_override",
            confidence="unknown",
            matched_rule="manual_override:reserved",
            ignored_from_totals=False,
        )

    for field_name, raw_value in (
        ("pluggy_raw_category", data.pluggy_raw_category),
        ("pluggy_raw_subcategory", data.pluggy_raw_subcategory),
        ("pluggy_raw_type", data.pluggy_raw_type),
    ):
        key = normalize_pluggy_value(raw_value)
        if key is None:
            continue
        rule = _CATEGORY_RULES.get(key) or _TYPE_RULES.get(key)
        if rule is not None:
            return _result_from_rule(rule, f"{field_name}:{raw_value}")

    description = normalize_description(data.description or "")
    if description:
        if any(pattern in description for pattern in _INVOICE_PAYMENT_PATTERNS):
            return _result_from_rule(
                _Rule("Pagamento de cartão", "credit_card_payment", confidence="medium"),
                "description:credit_card_payment",
                source="system_rule",
            )
        if any(pattern in description for pattern in _REFUND_PATTERNS):
            return _result_from_rule(
                _Rule("Estorno", "refund", confidence="medium"),
                "description:refund",
                source="system_rule",
            )

    if data.amount is not None:
        amount = Decimal(data.amount)
        if amount > 0 and (data.account_type or "").upper() == "BANK":
            return _result_from_rule(
                _Rule("Receitas", "income", confidence="medium"),
                "amount_sign:BANK:positive",
                source="system_rule",
            )
        if amount != 0:
            return _result_from_rule(
                _Rule("Outros", "expense", confidence="low"),
                "amount_sign:nonzero",
                source="fallback",
            )

    return ClassificationResult(
        internal_category="Outros",
        cashflow_type="unknown",
        source="fallback",
        confidence="low",
        matched_rule="fallback:unclassified",
        ignored_from_totals=False,
    )


def classify_transaction(tx: Transaction, account_type: Optional[str] = None) -> ClassificationResult:
    raw_category = tx.pluggy_raw_category if tx.pluggy_raw_category is not None else tx.category
    return classify_input(
        ClassificationInput(
            pluggy_raw_category=raw_category,
            pluggy_raw_subcategory=tx.pluggy_raw_subcategory,
            pluggy_raw_type=tx.pluggy_raw_type,
            pluggy_merchant=tx.pluggy_merchant,
            description=tx.description,
            amount=Decimal(tx.amount),
            account_type=account_type,
            is_user_overridden=bool(tx.is_user_overridden),
        )
    )


def classify_pluggy_payload(
    raw_tx: dict[str, Any],
    account_type: Optional[str] = None,
) -> ClassificationResult:
    raw_category = _first_present(raw_tx, "category", "categoryName")
    raw_subcategory = _first_present(raw_tx, "subcategory", "subCategory", "subcategoryName")
    raw_type = _first_present(raw_tx, "type", "transactionType")
    merchant = _extract_merchant(raw_tx)
    amount = raw_tx.get("amount")
    return classify_input(
        ClassificationInput(
            pluggy_raw_category=raw_category,
            pluggy_raw_subcategory=raw_subcategory,
            pluggy_raw_type=raw_type,
            pluggy_merchant=merchant,
            description=raw_tx.get("description"),
            amount=Decimal(str(amount)) if amount is not None else None,
            account_type=account_type,
        )
    )


def classification_payload_fields(raw_tx: dict[str, Any]) -> dict[str, Optional[str]]:
    return {
        "pluggy_raw_category": _first_present(raw_tx, "category", "categoryName"),
        "pluggy_raw_subcategory": _first_present(
            raw_tx,
            "subcategory",
            "subCategory",
            "subcategoryName",
        ),
        "pluggy_raw_type": _first_present(raw_tx, "type", "transactionType"),
        "pluggy_merchant": _extract_merchant(raw_tx),
    }


def serialize_transaction_classification(
    tx: Transaction,
    account_type: Optional[str] = None,
) -> dict[str, Any]:
    if (
        tx.internal_category
        and tx.cashflow_type
        and tx.classification_source
        and tx.classification_confidence
    ):
        return _persisted_transaction_classification(tx)

    result = classify_transaction(tx, account_type=account_type)
    values = result.transaction_values()
    return {
        "pluggy_raw_category": tx.pluggy_raw_category or tx.category,
        "pluggy_raw_subcategory": tx.pluggy_raw_subcategory,
        "pluggy_raw_type": tx.pluggy_raw_type,
        "pluggy_merchant": tx.pluggy_merchant,
        **values,
        "is_user_overridden": tx.is_user_overridden,
    }


def _persisted_transaction_classification(tx: Transaction) -> dict[str, Any]:
    return {
        "pluggy_raw_category": tx.pluggy_raw_category or tx.category,
        "pluggy_raw_subcategory": tx.pluggy_raw_subcategory,
        "pluggy_raw_type": tx.pluggy_raw_type,
        "pluggy_merchant": tx.pluggy_merchant,
        "internal_category": tx.internal_category,
        "cashflow_type": tx.cashflow_type,
        "classification_source": tx.classification_source,
        "classification_confidence": tx.classification_confidence,
        "classification_rule_key": tx.classification_rule_key,
        "ignored_from_totals": tx.ignored_from_totals,
        "is_user_overridden": tx.is_user_overridden,
    }


def _result_from_rule(
    rule: _Rule,
    matched_rule: str,
    source: str = "pluggy_rule",
) -> ClassificationResult:
    ignored = (
        rule.ignored_from_totals
        if rule.ignored_from_totals is not None
        else rule.cashflow_type in IGNORED_CASHFLOW_TYPES
    )
    return ClassificationResult(
        internal_category=rule.internal_category,
        cashflow_type=rule.cashflow_type,
        source=source,
        confidence=rule.confidence,
        matched_rule=matched_rule,
        ignored_from_totals=ignored,
    )


def _first_present(raw_tx: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = raw_tx.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _extract_merchant(raw_tx: dict[str, Any]) -> Optional[str]:
    merchant = raw_tx.get("merchant")
    if isinstance(merchant, dict):
        for key in ("name", "businessName", "tradingName"):
            value = merchant.get(key)
            if value:
                return str(value)
    if merchant:
        return str(merchant)
    return _first_present(raw_tx, "merchantName", "merchant_name")
