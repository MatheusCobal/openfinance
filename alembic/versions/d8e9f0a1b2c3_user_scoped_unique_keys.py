"""scope monthly snapshots and unique financial keys by user

Revision ID: d8e9f0a1b2c3
Revises: c1d2e3f4a5b6
Create Date: 2026-06-19 22:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SNAPSHOT_TABLES = {
    "creditcardinvoicemonth": [
        ("total", sa.Numeric),
        ("payment_count", sa.Integer),
    ],
    "bankincomemonth": [
        ("total", sa.Numeric),
        ("income_count", sa.Integer),
    ],
    "monthlybalancemonth": [
        ("income", sa.Numeric),
        ("card_spend", sa.Numeric),
        ("invoice_paid", sa.Numeric),
        ("net_by_purchase_month", sa.Numeric),
        ("net_cashflow", sa.Numeric),
        ("income_count", sa.Integer),
        ("card_spend_count", sa.Integer),
        ("invoice_payment_count", sa.Integer),
    ],
}


def _unique_name(table_name: str) -> str:
    return f"uq_{table_name}_user_month"


def _rebuild_snapshot_for_user_scope(table_name: str, value_specs: list[tuple]) -> None:
    value_columns = [
        sa.Column(column_name, column_type(), nullable=False)
        for column_name, column_type in value_specs
    ]
    legacy_table = f"_{table_name}_global_month"
    op.rename_table(table_name, legacy_table)
    op.drop_index(f"ix_{table_name}_year_month", table_name=legacy_table)
    op.drop_index(f"ix_{table_name}_user_id", table_name=legacy_table)

    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.String(), nullable=False),
        *value_columns,
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "year_month", name=_unique_name(table_name)),
    )

    copied_columns = [
        "year_month",
        *(column.name for column in value_columns),
        "captured_at",
        "updated_at",
        "user_id",
    ]
    column_list = ", ".join(copied_columns)
    op.execute(
        sa.text(
            f'INSERT INTO "{table_name}" ({column_list}) '
            f'SELECT {column_list} FROM "{legacy_table}"'
        )
    )
    op.drop_table(legacy_table)
    op.create_index(f"ix_{table_name}_year_month", table_name, ["year_month"], unique=False)
    op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"], unique=False)


def _restore_global_month_snapshot(table_name: str, value_specs: list[tuple]) -> None:
    value_columns = [
        sa.Column(column_name, column_type(), nullable=False)
        for column_name, column_type in value_specs
    ]
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            f'SELECT year_month FROM "{table_name}" '
            "GROUP BY year_month HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"cannot downgrade {table_name}: multiple users have snapshot {duplicate[0]}"
        )

    scoped_table = f"_{table_name}_user_month"
    op.rename_table(table_name, scoped_table)
    op.drop_index(f"ix_{table_name}_year_month", table_name=scoped_table)
    op.drop_index(f"ix_{table_name}_user_id", table_name=scoped_table)

    op.create_table(
        table_name,
        sa.Column("year_month", sa.String(), nullable=False),
        *value_columns,
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("year_month"),
    )
    copied_columns = [
        "year_month",
        *(column.name for column in value_columns),
        "captured_at",
        "updated_at",
        "user_id",
    ]
    column_list = ", ".join(copied_columns)
    op.execute(
        sa.text(
            f'INSERT INTO "{table_name}" ({column_list}) '
            f'SELECT {column_list} FROM "{scoped_table}"'
        )
    )
    op.drop_table(scoped_table)
    op.create_index(f"ix_{table_name}_year_month", table_name, ["year_month"], unique=False)
    op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"], unique=False)


def upgrade() -> None:
    op.drop_index("ix_fixedcostcategory_name", table_name="fixedcostcategory")
    op.create_index(
        "ix_fixedcostcategory_name", "fixedcostcategory", ["name"], unique=False
    )
    op.create_index(
        "uq_fixedcostcategory_user_name",
        "fixedcostcategory",
        ["user_id", "name"],
        unique=True,
    )

    op.drop_index(
        "ix_ignoreddescriptionrule_pattern_normalized",
        table_name="ignoreddescriptionrule",
    )
    op.create_index(
        "ix_ignoreddescriptionrule_pattern_normalized",
        "ignoreddescriptionrule",
        ["pattern_normalized"],
        unique=False,
    )
    op.create_index(
        "uq_ignoreddescriptionrule_user_pattern",
        "ignoreddescriptionrule",
        ["user_id", "pattern_normalized"],
        unique=True,
    )

    with op.batch_alter_table("variable_budgets", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_variablebudget_month_category", type_="unique")
        batch_op.create_unique_constraint(
            "uq_variablebudget_user_month_category",
            ["user_id", "year_month", "category"],
        )

    for table_name, value_columns in _SNAPSHOT_TABLES.items():
        _rebuild_snapshot_for_user_scope(table_name, value_columns)


def downgrade() -> None:
    for table_name, value_columns in reversed(_SNAPSHOT_TABLES.items()):
        _restore_global_month_snapshot(table_name, value_columns)

    with op.batch_alter_table("variable_budgets", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_variablebudget_user_month_category", type_="unique")
        batch_op.create_unique_constraint(
            "uq_variablebudget_month_category",
            ["year_month", "category"],
        )

    op.drop_index(
        "uq_ignoreddescriptionrule_user_pattern",
        table_name="ignoreddescriptionrule",
    )
    op.drop_index(
        "ix_ignoreddescriptionrule_pattern_normalized",
        table_name="ignoreddescriptionrule",
    )
    op.create_index(
        "ix_ignoreddescriptionrule_pattern_normalized",
        "ignoreddescriptionrule",
        ["pattern_normalized"],
        unique=True,
    )

    op.drop_index("uq_fixedcostcategory_user_name", table_name="fixedcostcategory")
    op.drop_index("ix_fixedcostcategory_name", table_name="fixedcostcategory")
    op.create_index(
        "ix_fixedcostcategory_name", "fixedcostcategory", ["name"], unique=True
    )
