"""Seed the Category and CategoryRule tables with the agreed defaults.

Idempotent: running twice does not duplicate rows. Edit CATEGORIES below to
change the mapping; rerun to apply.
"""
from sqlmodel import Session, select

from app.database import engine, init_db
from app.models import Category, CategoryRule

# Each entry: (name, color, sort_order, [pluggy_categories]).
# Pluggy category strings come from their taxonomy and are matched exactly
# against the Transaction.category field. Anything not listed here falls into
# "Outros" (last entry, no rules).
CATEGORIES = [
    (
        "Alimentação",
        "#10b981",  # emerald
        10,
        [
            "Eating out",
            "Food and drinks",
            "Food delivery",
            "Groceries",
            "Delivery",
            "Supermarket",
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
            "Car rental",
            "Auto insurance",
        ],
    ),
    (
        "Saúde",
        "#ef4444",  # red
        30,
        [
            "Healthcare",
            "Pharmacy",
            "Pet supplies and vet",
            "Medical",
            "Dentist",
            "Hospital",
            "Health insurance",
            "Gym",
            "Gyms and fitness centers",
            "Wellness and fitness",
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
            "Rent",
            "Electricity",
            "Water",
            "Internet",
            "Phone",
            "Furniture",
            "Home improvement",
            "Cleaning",
            "Services",
            "Office supplies",
        ],
    ),
    (
        "Objetos",
        "#8b5cf6",  # violet
        50,
        [
            "Electronics",
            "Clothing",
            "Bookstore",
            "Shopping",
            "Accessories",
            "Shoes",
            "Sportswear",
            "Beauty",
            "Cosmetics",
            "Kids and toys",
        ],
    ),
    (
        "Lazer",
        "#ec4899",  # pink
        60,
        [
            "Entertainment",
            "Leisure",
            "Digital services",
            "Travel",
            "Accomodation",
            "Streaming",
            "Video streaming",
            "Music streaming",
            "Hotels",
            "Cinema",
            "Cinema, theater and concerts",
            "Tickets",
            "Mileage programs",
            "Games",
            "Subscriptions",
            "Events",
            "Hobbies",
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
            "Online courses",
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
        ],
    ),
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


def main() -> None:
    init_db()
    with Session(engine) as session:
        for name, color, sort_order, pluggy_categories in CATEGORIES:
            category = upsert_category(session, name, color, sort_order)
            for pc in pluggy_categories:
                upsert_rule(session, pc, category.id)
        session.commit()

    total_categories = sum(1 for c in CATEGORIES)
    total_rules = sum(len(c[3]) for c in CATEGORIES)
    print(f"Seeded {total_categories} categories and {total_rules} rules.")


if __name__ == "__main__":
    main()
