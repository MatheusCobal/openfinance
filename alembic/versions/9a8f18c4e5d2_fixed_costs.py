"""fixed_costs

Revision ID: 9a8f18c4e5d2
Revises: fadace8cdbc2
Create Date: 2026-05-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "9a8f18c4e5d2"
down_revision: Union[str, Sequence[str], None] = "fadace8cdbc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fixedcostcategory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("color", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fixedcostcategory_name"),
        "fixedcostcategory",
        ["name"],
        unique=True,
    )
    op.create_table(
        "fixedcost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["fixedcostcategory.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fixedcost_active"), "fixedcost", ["active"], unique=False
    )
    op.create_index(
        op.f("ix_fixedcost_category_id"),
        "fixedcost",
        ["category_id"],
        unique=False,
    )
    op.create_table(
        "fixedcostoverride",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixed_cost_id", sa.Integer(), nullable=False),
        sa.Column("year_month", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["fixed_cost_id"], ["fixedcost.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fixed_cost_id",
            "year_month",
            name="uq_fixedcostoverride_entry_month",
        ),
    )
    op.create_index(
        op.f("ix_fixedcostoverride_fixed_cost_id"),
        "fixedcostoverride",
        ["fixed_cost_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fixedcostoverride_year_month"),
        "fixedcostoverride",
        ["year_month"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_fixedcostoverride_year_month"), table_name="fixedcostoverride"
    )
    op.drop_index(
        op.f("ix_fixedcostoverride_fixed_cost_id"),
        table_name="fixedcostoverride",
    )
    op.drop_table("fixedcostoverride")
    op.drop_index(op.f("ix_fixedcost_category_id"), table_name="fixedcost")
    op.drop_index(op.f("ix_fixedcost_active"), table_name="fixedcost")
    op.drop_table("fixedcost")
    op.drop_index(op.f("ix_fixedcostcategory_name"), table_name="fixedcostcategory")
    op.drop_table("fixedcostcategory")
