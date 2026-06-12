import datetime
import unittest
from decimal import Decimal

from app.models import Transaction
from app.services.credit_categories import (
    CREDIT_CATEGORY_LABELS,
    resolve_credit_category_from_pluggy,
    resolve_credit_internal_category,
)


class CreditCategoryResolverTest(unittest.TestCase):
    def resolve(self, **kwargs):
        return resolve_credit_category_from_pluggy(**kwargs)

    def test_final_taxonomy_has_at_most_ten_groups(self):
        self.assertLessEqual(len(CREDIT_CATEGORY_LABELS), 10)
        self.assertEqual(len(set(CREDIT_CATEGORY_LABELS)), len(CREDIT_CATEGORY_LABELS))

    def test_pluggy_category_direct_mappings(self):
        cases = [
            ("Eating out", "Alimentação"),
            ("Groceries", "Alimentação"),
            ("Pharmacy", "Saúde"),
            ("Healthcare", "Saúde"),
            ("Pet supplies and vet", "Pet"),
            ("Gas stations", "Transporte"),
            ("Shopping", "Compras pessoais"),
            ("Electronics", "Compras pessoais"),
            ("Clothing", "Compras pessoais"),
            ("Airport and airlines", "Lazer / Viagem"),
            ("Accomodation", "Lazer / Viagem"),
            ("Mileage programs", "Lazer / Viagem"),
        ]
        for raw_category, expected in cases:
            with self.subTest(raw_category=raw_category):
                self.assertEqual(
                    self.resolve(pluggy_raw_category=raw_category),
                    expected,
                )

    def test_description_is_used_only_for_clear_cases(self):
        cases = [
            ("IFD*Totem Porto Burger", "Alimentação"),
            ("Farmacia Sao Joao", "Saúde"),
            ("Uber Trip", "Transporte"),
            ("Posto gasolina", "Transporte"),
            ("Netflix streaming", "Assinaturas"),
            ("Leroy Merlin material de construcao", "Casa"),
            ("Cobasi racao", "Pet"),
            ("Curso online Python", "Educação"),
            ("Latam passagem aeroporto", "Lazer / Viagem"),
            ("Loja Renner roupas", "Compras pessoais"),
        ]
        for description, expected in cases:
            with self.subTest(description=description):
                self.assertEqual(
                    self.resolve(pluggy_raw_category=None, description=description),
                    expected,
                )

    def test_legacy_internal_category_is_only_fallback(self):
        self.assertEqual(
            self.resolve(
                pluggy_raw_category=None,
                current_internal_category="Presentes",
            ),
            "Compras pessoais",
        )
        self.assertEqual(
            self.resolve(
                pluggy_raw_category=None,
                current_internal_category="Beleza / Cuidados pessoais",
            ),
            "Compras pessoais",
        )
        self.assertEqual(
            self.resolve(
                pluggy_raw_category="Shopping",
                current_internal_category="Pet",
            ),
            "Compras pessoais",
        )

    def test_unknown_services_and_empty_values_fall_back_to_other_fees(self):
        self.assertEqual(
            self.resolve(pluggy_raw_category=None),
            "Outros / Taxas",
        )
        self.assertEqual(
            self.resolve(pluggy_raw_category="Something brand new"),
            "Outros / Taxas",
        )
        self.assertEqual(
            self.resolve(pluggy_raw_category="Services"),
            "Outros / Taxas",
        )
        self.assertEqual(
            self.resolve(
                pluggy_raw_category="Services",
                description="Netflix streaming",
            ),
            "Assinaturas",
        )

    def test_invoice_payment_does_not_become_purchase_category(self):
        self.assertEqual(
            self.resolve(
                pluggy_raw_category="Credit card payment",
                description="Pagamento recebido",
                current_internal_category="Pagamento de cartão",
            ),
            "Outros / Taxas",
        )

    def test_bank_transaction_is_not_resolved_as_credit_category(self):
        tx = Transaction(
            id="bank-shopping",
            account_id="bank-1",
            date=datetime.date(2026, 6, 12),
            amount=Decimal("-10"),
            description="Amazon",
            pluggy_raw_category="Shopping",
            internal_category="Alimentação",
        )

        self.assertEqual(
            resolve_credit_internal_category(tx, account_type="BANK"),
            "Alimentação",
        )


if __name__ == "__main__":
    unittest.main()
