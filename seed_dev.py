"""Throwaway helper to populate the local DB with sample data for UI testing."""
from datetime import date, timedelta
from decimal import Decimal

from app.database import engine, init_db
from app.models import Account, Item, Transaction
from sqlmodel import Session

SAMPLE_TRANSACTIONS = [
    ("iFood", "Food and drinks", "35.90", 0),
    ("Restaurante Sushi Yama", "Food and drinks", "127.50", 1),
    ("Padaria Estrela", "Food and drinks", "18.40", 2),
    ("Starbucks", "Food and drinks", "32.00", 3),
    ("Mercado Pao de Acucar", "Supermarket", "284.55", 1),
    ("Hortifruti", "Supermarket", "92.30", 4),
    ("Uber trip", "Transportation", "24.50", 0),
    ("99 Pop", "Transportation", "18.90", 2),
    ("Posto Shell", "Transportation", "230.00", 5),
    ("Netflix", "Entertainment", "55.90", 7),
    ("Spotify Premium", "Entertainment", "21.90", 8),
    ("Cinemark", "Entertainment", "48.00", 3),
    ("Amazon BR", "Shopping", "189.90", 6),
    ("Magazine Luiza", "Shopping", "459.00", 10),
    ("Zara", "Shopping", "299.80", 12),
    ("Drogaria Sao Paulo", "Health", "78.40", 4),
    ("Smart Fit", "Health", "99.90", 9),
    ("Conta de luz - Enel", "Bills", "187.65", 6),
    ("Conta de internet", "Bills", "129.90", 11),
    ("Airbnb - Floripa", "Travel", "1240.00", 15),
    ("LATAM passagem", "Travel", "892.30", 20),
    ("Compra avulsa qualquer", None, "45.00", 2),
]


def main() -> None:
    init_db()
    with Session(engine) as session:
        # Replace any old sample rows
        session.query(Transaction).delete()
        session.query(Account).delete()
        session.query(Item).delete()

        item = Item(id="sample-item", connector_id=2, connector_name="Pluggy Bank", status="UPDATED")
        account = Account(
            id="sample-credit",
            item_id="sample-item",
            name="Cartao Sample",
            type="CREDIT",
            subtype="CREDIT_CARD",
            marketing_name="Sample Black",
        )
        session.add(item)
        session.add(account)

        today = date.today()
        for i, (description, category, amount, days_ago) in enumerate(SAMPLE_TRANSACTIONS):
            session.add(
                Transaction(
                    id=f"sample-tx-{i}",
                    account_id=account.id,
                    date=today - timedelta(days=days_ago),
                    amount=Decimal(amount),
                    description=description,
                    category=category,
                    currency_code="BRL",
                )
            )
        session.commit()
    print(f"Seeded {len(SAMPLE_TRANSACTIONS)} transactions.")


if __name__ == "__main__":
    main()
