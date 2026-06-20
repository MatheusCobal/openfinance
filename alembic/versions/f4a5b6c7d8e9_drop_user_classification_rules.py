"""drop user classification rules

Revision ID: f4a5b6c7d8e9
Revises: d8e9f0a1b2c3
Create Date: 2026-06-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "user_classification_rules"


def upgrade() -> None:
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE)


def downgrade() -> None:
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("account_type_scope", sa.String(), nullable=False),
        sa.Column("match_pluggy_category", sa.String(), nullable=True),
        sa.Column("match_pluggy_subcategory", sa.String(), nullable=True),
        sa.Column("match_pluggy_type", sa.String(), nullable=True),
        sa.Column("match_merchant", sa.String(), nullable=True),
        sa.Column("match_description", sa.String(), nullable=True),
        sa.Column("match_amount_sign", sa.String(), nullable=False),
        sa.Column("target_internal_category", sa.String(), nullable=False),
        sa.Column("target_cashflow_type", sa.String(), nullable=False),
        sa.Column("ignored_from_totals", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "user_id",
        "enabled",
        "priority",
        "account_type_scope",
        "match_pluggy_category",
    ):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column], unique=False)
