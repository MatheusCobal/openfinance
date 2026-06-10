"""stabilize_user_classification_rules_table

Rename the table created by early local 10D-D runs from SQLModel's default
``userclassificationrule`` to the intended ``user_classification_rules``.

This migration is intentionally narrow: it only normalizes the rules table name
and its indexes. It does not alter transactions, raw Pluggy fields or financial
data.

Revision ID: d1e2f3a4b5c6
Revises: c8d3f1a6b240
Create Date: 2026-06-10 13:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c8d3f1a6b240"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "user_classification_rules"
LEGACY_TABLE = "userclassificationrule"

INDEXES = (
    ("ix_user_classification_rules_enabled", "enabled"),
    ("ix_user_classification_rules_priority", "priority"),
    ("ix_user_classification_rules_account_type_scope", "account_type_scope"),
    ("ix_user_classification_rules_match_pluggy_category", "match_pluggy_category"),
)
LEGACY_INDEXES = (
    "ix_userclassificationrule_enabled",
    "ix_userclassificationrule_priority",
    "ix_userclassificationrule_account_type_scope",
    "ix_userclassificationrule_match_pluggy_category",
)


def _table_names() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("account_type_scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("match_pluggy_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("match_pluggy_subcategory", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("match_pluggy_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("match_merchant", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("match_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("match_amount_sign", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_internal_category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_cashflow_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ignored_from_totals", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _ensure_indexes(table_name: str = TABLE) -> None:
    existing = _index_names(table_name)
    for index_name, column_name in INDEXES:
        if index_name not in existing:
            op.create_index(index_name, table_name, [column_name], unique=False)


def _drop_indexes(table_name: str, names: tuple[str, ...]) -> None:
    existing = _index_names(table_name)
    for index_name in names:
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    tables = _table_names()
    if TABLE not in tables and LEGACY_TABLE in tables:
        _drop_indexes(LEGACY_TABLE, LEGACY_INDEXES)
        op.rename_table(LEGACY_TABLE, TABLE)
    elif TABLE not in tables:
        _create_table()

    _ensure_indexes(TABLE)


def downgrade() -> None:
    tables = _table_names()
    if TABLE not in tables:
        return

    _drop_indexes(TABLE, tuple(index_name for index_name, _ in INDEXES))

    if LEGACY_TABLE not in tables:
        op.rename_table(TABLE, LEGACY_TABLE)

    existing = _index_names(LEGACY_TABLE)
    for index_name, column_name in zip(
        LEGACY_INDEXES,
        (
            "enabled",
            "priority",
            "account_type_scope",
            "match_pluggy_category",
        ),
    ):
        if index_name not in existing:
            op.create_index(index_name, LEGACY_TABLE, [column_name], unique=False)
