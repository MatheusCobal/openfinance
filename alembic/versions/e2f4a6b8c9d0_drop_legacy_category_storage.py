"""drop_legacy_category_storage

Revision ID: e2f4a6b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-06-10 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "e2f4a6b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_TABLES = (
    "budgetoverride",
    "budget",
    "descriptioncategoryrule",
    "categoryrule",
    "category",
)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if table_name in _table_names() and index_name in _index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_table_if_exists(table_name: str) -> None:
    if table_name in _table_names():
        op.drop_table(table_name)


def upgrade() -> None:
    _drop_index_if_exists("ix_budgetoverride_year_month", "budgetoverride")
    _drop_index_if_exists("ix_budgetoverride_category_id", "budgetoverride")
    _drop_table_if_exists("budgetoverride")

    _drop_index_if_exists("ix_budget_category_id", "budget")
    _drop_table_if_exists("budget")

    _drop_index_if_exists(
        "ix_descriptioncategoryrule_pattern_normalized",
        "descriptioncategoryrule",
    )
    _drop_index_if_exists("ix_descriptioncategoryrule_category_id", "descriptioncategoryrule")
    _drop_table_if_exists("descriptioncategoryrule")

    _drop_index_if_exists("ix_categoryrule_pluggy_category", "categoryrule")
    _drop_index_if_exists("ix_categoryrule_category_id", "categoryrule")
    _drop_table_if_exists("categoryrule")

    _drop_index_if_exists("ix_category_parent_id", "category")
    _drop_index_if_exists("ix_category_name", "category")
    _drop_table_if_exists("category")


def downgrade() -> None:
    existing = _table_names()
    if "category" not in existing:
        op.create_table(
            "category",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("color", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["parent_id"], ["category.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_category_name", "category", ["name"], unique=True)
        op.create_index("ix_category_parent_id", "category", ["parent_id"], unique=False)

    if "categoryrule" not in existing:
        op.create_table(
            "categoryrule",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pluggy_category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_categoryrule_category_id", "categoryrule", ["category_id"])
        op.create_index(
            "ix_categoryrule_pluggy_category",
            "categoryrule",
            ["pluggy_category"],
            unique=True,
        )

    if "descriptioncategoryrule" not in existing:
        op.create_table(
            "descriptioncategoryrule",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pattern", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("pattern_normalized", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_descriptioncategoryrule_category_id",
            "descriptioncategoryrule",
            ["category_id"],
        )
        op.create_index(
            "ix_descriptioncategoryrule_pattern_normalized",
            "descriptioncategoryrule",
            ["pattern_normalized"],
            unique=True,
        )

    if "budget" not in existing:
        op.create_table(
            "budget",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("monthly_target", sa.Numeric(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_budget_category_id", "budget", ["category_id"], unique=True)

    if "budgetoverride" not in existing:
        op.create_table(
            "budgetoverride",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("year_month", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("monthly_target", sa.Numeric(), nullable=False),
            sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("category_id", "year_month", name="uq_budgetoverride_month"),
        )
        op.create_index("ix_budgetoverride_category_id", "budgetoverride", ["category_id"])
        op.create_index("ix_budgetoverride_year_month", "budgetoverride", ["year_month"])
