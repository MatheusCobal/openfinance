import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: str = Field(primary_key=True)
    connector_id: int
    connector_name: Optional[str] = None
    status: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    name: str
    type: str
    subtype: Optional[str] = None
    marketing_name: Optional[str] = None
    number: Optional[str] = None


class Transaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    date: datetime.date = Field(index=True)
    amount: Decimal
    description: str
    category: Optional[str] = None
    currency_code: str = "BRL"


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    color: str
    sort_order: int = 0


class CategoryRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pluggy_category: str = Field(unique=True, index=True)
    category_id: int = Field(foreign_key="category.id", index=True)


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", unique=True, index=True)
    monthly_target: Decimal


class BudgetOverride(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("category_id", "year_month", name="uq_budgetoverride_month"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    year_month: str = Field(index=True)
    monthly_target: Decimal
