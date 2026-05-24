"""Seed the Category and CategoryRule tables with the agreed defaults.

Idempotent: running twice does not duplicate rows. Edit CATEGORIES below to
change the mapping; rerun to apply. Note: this script does NOT delete
categories or rules that are removed from CATEGORIES — do that manually with
SQL if you want a clean state.
"""
from sqlmodel import Session, select

from app.categorization import normalize_description
from app.database import engine, init_db
from app.models import Category, CategoryRule, IgnoredDescriptionRule

# Each entry: (name, color, sort_order, [pluggy_categories]).
# Pluggy category strings come from their taxonomy and are matched exactly
# against the Transaction.category field. Anything not listed here falls into
# "Outros" (last entry, no rules).
CATEGORIES = [
    (
        "Mercado",
        "#16a34a",  # green-600
        10,
        [
            "Groceries",
            "Supermarket",
        ],
    ),
    (
        "Restaurantes",
        "#10b981",  # emerald
        15,
        [
            "Eating out",
            "Food and drinks",
            "Food delivery",
            "Delivery",
            "Restaurants",
            "Coffee shop",
            "Bakery",
            "Bars",
            "Fast food",
        ],
    ),
    (
        "Transporte",
        "#f97316",  # orange
        20,
        [
            "Gas stations",
            "Transportation",
            "Auto",
            "Automotive",
            "Uber",
            "Mobility",
            "Public transport",
            "Taxi",
            "Taxi and ride-hailing",
            "Parking",
            "Tolls",
            "Tolls and in vehicle payment",
            "Car rental",
            "Auto insurance",
            "Vehicle maintenance",
        ],
    ),
    (
        "Saúde",
        "#ef4444",  # red
        30,
        [
            "Healthcare",
            "Pharmacy",
            "Medical",
            "Dentist",
            "Hospital",
            "Hospital clinics and labs",
            "Health insurance",
            "Gym",
            "Gyms and fitness centers",
            "Wellness",
            "Wellness and fitness",
        ],
    ),
    (
        "Pets",
        "#14b8a6",  # teal
        35,
        [
            "Pet supplies and vet",
            "Pets",
        ],
    ),
    (
        "Casa",
        "#3b82f6",  # blue
        40,
        [
            "Utilities",
            "Bills",
            "Telecommunications",
            "Houseware",
            "Home",
            "Housing",
            "Rent",
            "Electricity",
            "Water",
            "Internet",
            "Phone",
            "Furniture",
            "Home improvement",
            "Cleaning",
        ],
    ),
    (
        "Lazer",
        "#ec4899",  # pink
        60,
        [
            "Entertainment",
            "Leisure",
            "Travel",
            "Accomodation",
            "Airport and airlines",
            "Hotels",
            "Cinema",
            "Cinema, theater and concerts",
            "Tickets",
            "Stadiums and arenas",
            "Mileage programs",
            "Games",
            "Events",
            "Hobbies",
        ],
    ),
    (
        "Assinaturas",
        "#06b6d4",  # cyan
        65,
        [
            "Digital services",
            "Streaming",
            "Video streaming",
            "Music streaming",
            "Subscriptions",
        ],
    ),
    (
        "Educação",
        "#eab308",  # yellow
        70,
        [
            "School",
            "Courses",
            "Education",
            "Books",
            "Bookstore",
            "Online courses",
            "Online Courses",
            "Tuition",
        ],
    ),
    (
        "Transferências",
        "#94a3b8",  # slate
        80,
        [
            "Transfers",
            "Investments",
            "Credit card payment",
            "Credit card fees",
            "Card payments",
            "Loan payment",
            "Withdrawal",
            "Deposit",
            "PIX",
            "TED",
            "DOC",
            "Tax on financial operations",
        ],
    ),
    (
        "Outros",
        "#64748b",  # darker slate (fallback for unmapped)
        999,
        [
            "Donations",
            "Insurance",
            "Services",
            "Office supplies",
            # Absorbed from the old "Objetos" category:
            "Electronics",
            "Clothing",
            "Shopping",
            "Online shopping",
            "Accessories",
            "Shoes",
            "Sportswear",
            "Sports goods",
            "Beauty",
            "Cosmetics",
            "Kids and toys",
        ],
    ),
]

IGNORED_DESCRIPTION_PATTERNS = [
    "PAGAMENTO COM SALDO",
    "Pagamento recebido",
]


def upsert_category(session: Session, name: str, color: str, sort_order: int) -> Category:
    existing = session.exec(select(Category).where(Category.name == name)).first()
    if existing:
        existing.color = color
        existing.sort_order = sort_order
        session.add(existing)
        return existing
    category = Category(name=name, color=color, sort_order=sort_order)
    session.add(category)
    session.flush()  # ensure id is populated for FK use below
    return category


def upsert_rule(session: Session, pluggy_category: str, category_id: int) -> None:
    existing = session.exec(
        select(CategoryRule).where(CategoryRule.pluggy_category == pluggy_category)
    ).first()
    if existing:
        if existing.category_id != category_id:
            existing.category_id = category_id
            session.add(existing)
        return
    session.add(CategoryRule(pluggy_category=pluggy_category, category_id=category_id))


def upsert_ignored_description_rule(session: Session, pattern: str) -> None:
    pattern_normalized = normalize_description(pattern)
    existing = session.exec(
        select(IgnoredDescriptionRule).where(
            IgnoredDescriptionRule.pattern_normalized == pattern_normalized
        )
    ).first()
    if existing:
        if existing.pattern != pattern:
            existing.pattern = pattern
            session.add(existing)
        return
    session.add(
        IgnoredDescriptionRule(
            pattern=pattern,
            pattern_normalized=pattern_normalized,
        )
    )


def main() -> None:
    init_db()
    with Session(engine) as session:
        for name, color, sort_order, pluggy_categories in CATEGORIES:
            category = upsert_category(session, name, color, sort_order)
            for pc in pluggy_categories:
                upsert_rule(session, pc, category.id)
        for pattern in IGNORED_DESCRIPTION_PATTERNS:
            upsert_ignored_description_rule(session, pattern)
        session.commit()

    total_categories = sum(1 for c in CATEGORIES)
    total_rules = sum(len(c[3]) for c in CATEGORIES)
    total_ignored_rules = len(IGNORED_DESCRIPTION_PATTERNS)
    print(
        "Seeded "
        f"{total_categories} categories, "
        f"{total_rules} rules and "
        f"{total_ignored_rules} ignored transaction rules."
    )


if __name__ == "__main__":
    main()
