import datetime
from decimal import Decimal
from typing import Optional

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
