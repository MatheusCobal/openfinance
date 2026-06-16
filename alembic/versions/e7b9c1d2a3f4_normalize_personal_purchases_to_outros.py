"""normalize_personal_purchases_to_outros

Revision ID: e7b9c1d2a3f4
Revises: a4b8c2d6e0f1
Create Date: 2026-06-16 00:00:00.000000

"""

from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b9c1d2a3f4"
down_revision: Union[str, Sequence[str], None] = "a4b8c2d6e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_CATEGORIES = (
    "Compras pessoais",
    "compras pessoais",
    "Outros / Taxas",
    "outros / taxas",
)


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa.inspect(bind).get_table_names()


def _normalize_simple_column(table_name: str, column_name: str) -> None:
    if not _table_exists(table_name):
        return
    bind = op.get_bind()
    quoted_table = bind.dialect.identifier_preparer.quote(table_name)
    quoted_column = bind.dialect.identifier_preparer.quote(column_name)
    bind.execute(
        sa.text(
            f"""
            UPDATE {quoted_table}
            SET {quoted_column} = 'Outros'
            WHERE {quoted_column} IN :legacy_categories
            """
        ).bindparams(sa.bindparam("legacy_categories", expanding=True)),
        {"legacy_categories": LEGACY_CATEGORIES},
    )


def _normalize_variable_budgets() -> None:
    if not _table_exists("variable_budgets"):
        return

    bind = op.get_bind()
    tracked_categories = (*LEGACY_CATEGORIES, "Outros")
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, year_month, category, target_amount
                FROM variable_budgets
                WHERE category IN :tracked_categories
                ORDER BY year_month, id
                """
            ).bindparams(sa.bindparam("tracked_categories", expanding=True)),
            {"tracked_categories": tracked_categories},
        ).mappings()
    )

    rows_by_month = defaultdict(list)
    for row in rows:
        rows_by_month[row["year_month"]].append(row)

    legacy_set = set(LEGACY_CATEGORIES)
    for month_rows in rows_by_month.values():
        if not any(row["category"] in legacy_set for row in month_rows):
            continue

        target_total = sum(row["target_amount"] for row in month_rows)
        existing_outros = next(
            (row for row in month_rows if row["category"] == "Outros"),
            None,
        )
        winner = existing_outros or month_rows[0]
        delete_ids = [row["id"] for row in month_rows if row["id"] != winner["id"]]

        if delete_ids:
            bind.execute(
                sa.text("DELETE FROM variable_budgets WHERE id IN :delete_ids").bindparams(
                    sa.bindparam("delete_ids", expanding=True)
                ),
                {"delete_ids": delete_ids},
            )
        bind.execute(
            sa.text(
                """
                UPDATE variable_budgets
                SET category = 'Outros', target_amount = :target_total
                WHERE id = :winner_id
                """
            ),
            {"target_total": target_total, "winner_id": winner["id"]},
        )


def upgrade() -> None:
    _normalize_simple_column("transaction", "internal_category")
    _normalize_simple_column("user_classification_rules", "target_internal_category")
    _normalize_variable_budgets()


def downgrade() -> None:
    # The consolidation is intentionally not reversible: after multiple old
    # labels become "Outros", we cannot safely infer which rows used to be
    # "Compras pessoais" or "Outros / Taxas".
    pass
