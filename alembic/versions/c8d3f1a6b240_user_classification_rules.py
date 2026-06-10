"""user_classification_rules

Add the user_classification_rules table for 10D-D user-defined classification
rules. The migration is additive only: it creates one new table and does not
touch transactions, raw Pluggy fields or any legacy category storage.

Revision ID: c8d3f1a6b240
Revises: b7e4d2c9a10f
Create Date: 2026-06-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "c8d3f1a6b240"
down_revision: Union[str, Sequence[str], None] = "b7e4d2c9a10f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_classification_rules",
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
    op.create_index(
        op.f("ix_user_classification_rules_enabled"),
        "user_classification_rules",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_classification_rules_priority"),
        "user_classification_rules",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_classification_rules_account_type_scope"),
        "user_classification_rules",
        ["account_type_scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_classification_rules_match_pluggy_category"),
        "user_classification_rules",
        ["match_pluggy_category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_classification_rules_match_pluggy_category"),
        table_name="user_classification_rules",
    )
    op.drop_index(
        op.f("ix_user_classification_rules_account_type_scope"),
        table_name="user_classification_rules",
    )
    op.drop_index(
        op.f("ix_user_classification_rules_priority"),
        table_name="user_classification_rules",
    )
    op.drop_index(
        op.f("ix_user_classification_rules_enabled"),
        table_name="user_classification_rules",
    )
    op.drop_table("user_classification_rules")
