from __future__ import annotations

from typing import Iterable, Optional

from app.categorization import normalize_description
from app.models import Transaction


CREDIT_CATEGORY_LABELS = (
    "Alimentação",
    "Saúde",
    "Assinaturas",
    "Transporte",
    "Casa",
    "Pet",
    "Educação",
    "Lazer / Viagem",
    "Compras pessoais",
    "Outros / Taxas",
)

DEFAULT_CREDIT_CATEGORY = "Outros / Taxas"

_DIRECT_PLUGGY_CATEGORY_MAP = {
    "food": "Alimentação",
    "food delivery": "Alimentação",
    "food and drinks": "Alimentação",
    "delivery": "Alimentação",
    "restaurant": "Alimentação",
    "restaurants": "Alimentação",
    "eating out": "Alimentação",
    "market": "Alimentação",
    "grocery": "Alimentação",
    "groceries": "Alimentação",
    "pharmacy": "Saúde",
    "drugstore": "Saúde",
    "health": "Saúde",
    "healthcare": "Saúde",
    "medical": "Saúde",
    "hospital clinics and labs": "Saúde",
    "dentist": "Saúde",
    "digital services": "Assinaturas",
    "telecommunications": "Assinaturas",
    "internet": "Assinaturas",
    "mobile": "Assinaturas",
    "transport": "Transporte",
    "transportation": "Transporte",
    "taxi and ride hailing": "Transporte",
    "ride app": "Transporte",
    "fuel": "Transporte",
    "gas station": "Transporte",
    "gas stations": "Transporte",
    "parking": "Transporte",
    "automotive": "Transporte",
    "vehicle maintenance": "Transporte",
    "tolls and in vehicle payment": "Transporte",
    "houseware": "Casa",
    "housing": "Casa",
    "rent": "Casa",
    "electricity": "Casa",
    "water": "Casa",
    "pet": "Pet",
    "pet supplies and vet": "Pet",
    "bookstore": "Educação",
    "school": "Educação",
    "education": "Educação",
    "online courses": "Educação",
    "airport and airlines": "Lazer / Viagem",
    "accomodation": "Lazer / Viagem",
    "accommodation": "Lazer / Viagem",
    "mileage programs": "Lazer / Viagem",
    "travel": "Lazer / Viagem",
    "cinema theater and concerts": "Lazer / Viagem",
    "gaming": "Lazer / Viagem",
    "stadiums and arenas": "Lazer / Viagem",
    "tickets": "Lazer / Viagem",
    "leisure": "Lazer / Viagem",
    "shopping": "Compras pessoais",
    "online shopping": "Compras pessoais",
    "electronics": "Compras pessoais",
    "clothing": "Compras pessoais",
    "office supplies": "Compras pessoais",
    "sports goods": "Compras pessoais",
    "wellness and fitness": "Compras pessoais",
    "wellness": "Compras pessoais",
    "gyms and fitness centers": "Compras pessoais",
    "beauty": "Compras pessoais",
    "personal care": "Compras pessoais",
    "kids and toys": "Compras pessoais",
    "donations": "Compras pessoais",
    "tax": "Outros / Taxas",
    "taxes": "Outros / Taxas",
    "income taxes": "Outros / Taxas",
    "vehicle ownership taxes and fees": "Outros / Taxas",
    "fee": "Outros / Taxas",
    "fees": "Outros / Taxas",
    "credit card fees": "Outros / Taxas",
    "tax on financial operations": "Outros / Taxas",
    "insurance": "Outros / Taxas",
    "adjustment": "Outros / Taxas",
}

_LEGACY_INTERNAL_CATEGORY_MAP = {
    "alimentacao": "Alimentação",
    "saude": "Saúde",
    "assinaturas": "Assinaturas",
    "transporte": "Transporte",
    "casa": "Casa",
    "moradia": "Casa",
    "pet": "Pet",
    "educacao": "Educação",
    "lazer viagem": "Lazer / Viagem",
    "lazer": "Lazer / Viagem",
    "viagem": "Lazer / Viagem",
    "compras pessoais": "Compras pessoais",
    "compras": "Compras pessoais",
    "presentes": "Compras pessoais",
    "beleza cuidados pessoais": "Compras pessoais",
    "outros taxas": "Outros / Taxas",
    "impostos taxas": "Outros / Taxas",
    "financiamentos": "Outros / Taxas",
    "estorno": "Outros / Taxas",
    "ajustes": "Outros / Taxas",
    "ignorar": "Outros / Taxas",
    "outros": "Outros / Taxas",
}

_DESCRIPTION_PATTERNS = (
    (
        "Outros / Taxas",
        (
            "iof",
            "anuidade",
            "tarifa",
            "taxa",
            "imposto",
            "seguro",
            "insurance",
            "mensalidade plano do cartao",
            "plano do cartao",
            "ajuste",
        ),
    ),
    (
        "Alimentação",
        (
            "restaurante",
            "restaurant",
            "delivery",
            "mercado",
            "supermercado",
            "padaria",
            "cafe",
            "ifood",
            "alimentacao",
            "mcdonalds",
            "sushi",
            "pizza",
            "poke",
            "burger",
        ),
    ),
    (
        "Saúde",
        (
            "farmacia",
            "pharmacy",
            "clinica",
            "clinic",
            "hospital",
            "laboratorio",
            "medical",
            "medico",
            "dentista",
            "dentist",
            "exame",
            "saude",
        ),
    ),
    (
        "Assinaturas",
        (
            "streaming",
            "netflix",
            "spotify",
            "disney",
            "amazon prime",
            "google one",
            "icloud",
            "openai",
            "chatgpt",
            "software",
            "cloud",
            "assinatura digital",
            "mensalidade digital",
        ),
    ),
    (
        "Transporte",
        (
            "uber",
            "taxi",
            "combustivel",
            "posto",
            "gasolina",
            "etanol",
            "diesel",
            "estacionamento",
            "parking",
            "pedagio",
            "toll",
            "manutencao veicular",
            "vehicle maintenance",
        ),
    ),
    (
        "Casa",
        (
            "material de construcao",
            "construcao",
            "leroy merlin",
            "ferragem",
            "ferramenta",
            "moveis",
            "decoracao",
            "eletrodomestico",
            "itens domesticos",
        ),
    ),
    (
        "Pet",
        (
            "pet shop",
            "veterinario",
            "veterinaria",
            "racao",
            "banho e tosa",
            "cobasi",
            "petz",
        ),
    ),
    (
        "Educação",
        (
            "livro",
            "book",
            "curso",
            "course",
            "escola",
            "school",
            "faculdade",
            "educacao",
            "treinamento",
        ),
    ),
    (
        "Lazer / Viagem",
        (
            "hotel",
            "hospedagem",
            "passagem",
            "aeroporto",
            "airport",
            "airline",
            "latam",
            "milhas",
            "airbnb",
            "cinema",
            "show",
            "evento",
            "ingresso",
            "lazer",
            "viagem",
        ),
    ),
    (
        "Compras pessoais",
        (
            "roupa",
            "vestuario",
            "eletronico",
            "eletronicos",
            "cosmetico",
            "cosmeticos",
            "beleza",
            "cuidados pessoais",
            "presente",
            "shopping",
            "amazon",
            "mercadolivre",
            "decathlon",
            "renner",
        ),
    ),
)


def _normalize(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value)
    for token in ("_", "-", ",", "/", "&", ".", "*"):
        text = text.replace(token, " ")
    return normalize_description(text)


def _first_direct_match(values: Iterable[Optional[str]]) -> Optional[str]:
    for value in values:
        normalized = _normalize(value)
        if not normalized:
            continue
        category = _DIRECT_PLUGGY_CATEGORY_MAP.get(normalized)
        if category is not None:
            return category
    return None


def _first_description_match(values: Iterable[Optional[str]]) -> Optional[str]:
    haystack = " ".join(_normalize(value) for value in values if value)
    if not haystack:
        return None
    for category, patterns in _DESCRIPTION_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            return category
    return None


def _legacy_internal_category(value: Optional[str]) -> Optional[str]:
    normalized = _normalize(value)
    if not normalized:
        return None
    return _LEGACY_INTERNAL_CATEGORY_MAP.get(normalized)


def resolve_credit_category_from_pluggy(
    *,
    pluggy_raw_category: Optional[str],
    pluggy_raw_subcategory: Optional[str] = None,
    pluggy_raw_type: Optional[str] = None,
    pluggy_merchant: Optional[str] = None,
    description: Optional[str] = None,
    original_description: Optional[str] = None,
    current_internal_category: Optional[str] = None,
) -> str:
    direct = _first_direct_match(
        (
            pluggy_raw_category,
            pluggy_raw_subcategory,
            pluggy_raw_type,
            pluggy_merchant,
        )
    )
    if direct is not None:
        return direct

    described = _first_description_match(
        (
            pluggy_raw_subcategory,
            pluggy_raw_type,
            pluggy_merchant,
            description,
            original_description,
        )
    )
    if described is not None:
        return described

    legacy = _legacy_internal_category(current_internal_category)
    if legacy is not None:
        return legacy

    return DEFAULT_CREDIT_CATEGORY


def resolve_credit_internal_category(
    transaction: Transaction,
    *,
    account_type: Optional[str] = "CREDIT",
    current_internal_category: Optional[str] = None,
) -> str:
    if (account_type or "").upper() != "CREDIT":
        return current_internal_category or transaction.internal_category or DEFAULT_CREDIT_CATEGORY

    return resolve_credit_category_from_pluggy(
        pluggy_raw_category=transaction.pluggy_raw_category or transaction.category,
        pluggy_raw_subcategory=transaction.pluggy_raw_subcategory,
        pluggy_raw_type=transaction.pluggy_raw_type,
        pluggy_merchant=transaction.pluggy_merchant,
        description=transaction.description,
        current_internal_category=current_internal_category or transaction.internal_category,
    )


def credit_category_payload(category: str) -> dict[str, str]:
    return {
        "category": category,
        "effective_category": category,
        "resolved_category": category,
        "credit_category": category,
    }
