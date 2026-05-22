import csv
import io
import logging
import httpx
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.database import engine, get_session, init_db
from app.models import Account, Category, CategoryRule, Item, Transaction
from app.pluggy_client import pluggy

logger = logging.getLogger("openfinance")

STATIC_DIR = Path(__file__).parent / "static"
UNCATEGORIZED = "Sem categoria"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="OpenFinance Collector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/historico", include_in_schema=False)
def historico():
    return FileResponse(STATIC_DIR / "historico.html")


@app.get("/proximos", include_in_schema=False)
def proximos():
    return FileResponse(STATIC_DIR / "proximos.html")


@app.get("/health")
def health():
    return {"status": "ok"}


class ConnectTokenRequest(BaseModel):
    clientUserId: Optional[str] = None
    itemId: Optional[str] = None


@app.post("/connect-token")
def connect_token(body: Optional[ConnectTokenRequest] = None):
    body = body or ConnectTokenRequest()
    try:
        token = pluggy.create_connect_token(
            client_user_id=body.clientUserId, item_id=body.itemId
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise HTTPException(
                401,
                "Pluggy rejected the credentials. Check PLUGGY_CLIENT_ID and "
                "PLUGGY_CLIENT_SECRET in your .env file.",
            )
        raise HTTPException(
            502, f"Pluggy returned {exc.response.status_code}: {exc.response.text}"
        )
    return {"accessToken": token}


def _upsert_item(item_id: str, session: Session) -> Item:
    data = pluggy.get_item(item_id)
    item = session.get(Item, item_id)
    if item is None:
        item = Item(
            id=data["id"],
            connector_id=data["connector"]["id"],
            connector_name=data["connector"].get("name"),
            status=data["status"],
        )
        session.add(item)
    else:
        item.status = data["status"]
        item.connector_name = data["connector"].get("name")
    session.commit()
    session.refresh(item)
    return item


def _sync_item(item_id: str, session: Session) -> Dict[str, int]:
    raw_accounts = pluggy.list_accounts(item_id)
    credit_accounts = [a for a in raw_accounts if a["type"] == "CREDIT"]

    new_transactions = 0
    for raw_account in credit_accounts:
        if not session.get(Account, raw_account["id"]):
            session.add(
                Account(
                    id=raw_account["id"],
                    item_id=item_id,
                    name=raw_account["name"],
                    type=raw_account["type"],
                    subtype=raw_account.get("subtype"),
                    marketing_name=raw_account.get("marketingName"),
                    number=raw_account.get("number"),
                )
            )

        for raw_tx in pluggy.list_transactions(raw_account["id"]):
            if session.get(Transaction, raw_tx["id"]):
                continue
            session.add(
                Transaction(
                    id=raw_tx["id"],
                    account_id=raw_account["id"],
                    date=date.fromisoformat(raw_tx["date"][:10]),
                    amount=Decimal(str(raw_tx["amount"])),
                    description=raw_tx["description"],
                    category=raw_tx.get("category"),
                    currency_code=raw_tx.get("currencyCode") or "BRL",
                )
            )
            new_transactions += 1

    session.commit()
    return {
        "credit_accounts": len(credit_accounts),
        "new_transactions": new_transactions,
    }


@app.post("/items/{item_id}")
def register_item(item_id: str, session: Session = Depends(get_session)):
    return _upsert_item(item_id, session)


@app.post("/items/{item_id}/sync")
def sync_item(item_id: str, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if item is None:
        # Auto-register if Pluggy knows about it but we don't yet
        # (happens when the widget completes and frontend skips registration).
        item = _upsert_item(item_id, session)
    return _sync_item(item_id, session)


@app.post("/webhooks/pluggy")
async def pluggy_webhook(request: Request, background_tasks: BackgroundTasks):
    # Pluggy needs a 2xx within ~5 seconds. We acknowledge immediately and
    # process in the background.
    payload: Dict[str, Any] = await request.json()
    event = payload.get("event")
    item_id = payload.get("itemId")
    logger.info("pluggy webhook event=%s item=%s", event, item_id)

    if event in {"item/created", "item/updated"} and item_id:
        background_tasks.add_task(_handle_item_event, item_id)

    return {"received": True}


def _handle_item_event(item_id: str) -> None:
    try:
        with Session(engine) as session:
            _upsert_item(item_id, session)
            result = _sync_item(item_id, session)
        logger.info("synced item=%s result=%s", item_id, result)
    except Exception:
        logger.exception("failed to process item event item=%s", item_id)


@app.get("/items")
def list_items(session: Session = Depends(get_session)):
    return session.exec(select(Item)).all()


@app.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()


@app.get("/transactions")
def list_transactions(
    account_id: Optional[str] = None,
    category_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    query = select(Transaction).order_by(Transaction.date.desc())
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.date <= to_date)
    if not include_future and to_date is None:
        query = query.where(Transaction.date <= date.today())
    transactions = session.exec(query).all()

    def to_dict(tx: Transaction) -> Dict[str, Any]:
        cat = resolver.resolve(tx.category)
        return {
            **tx.model_dump(mode="json"),
            "custom_category_id": cat.id,
            "custom_category_name": cat.name,
            "custom_category_color": cat.color,
        }

    rows = [to_dict(tx) for tx in transactions]
    if category_id is not None:
        rows = [r for r in rows if r["custom_category_id"] == category_id]
    return rows


@app.get("/categories")
def list_categories(session: Session = Depends(get_session)):
    return CategoryResolver(session).all_categories()


@app.get("/export/transactions.csv")
def export_transactions_csv(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    session: Session = Depends(get_session),
):
    """Export transactions (filtered by the same params as /transactions) as CSV.

    Streamed so memory stays flat even for tens of thousands of rows.
    """
    resolver = CategoryResolver(session)
    query = select(Transaction).order_by(Transaction.date.desc())
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.date <= to_date)
    if not include_future and to_date is None:
        query = query.where(Transaction.date <= date.today())
    transactions = session.exec(query).all()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "date",
                "description",
                "amount",
                "currency",
                "pluggy_category",
                "category",
                "account_id",
                "transaction_id",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()

        for tx in transactions:
            cat = resolver.resolve(tx.category)
            writer.writerow(
                [
                    tx.date.isoformat(),
                    tx.description,
                    f"{abs(tx.amount):.2f}",
                    tx.currency_code,
                    tx.category or "",
                    cat.name,
                    tx.account_id,
                    tx.id,
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()

    filename = f"transactions-{date.today().isoformat()}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/upcoming")
def upcoming(session: Session = Depends(get_session)):
    """Future-dated transactions (parcelas a vencer) grouped by month → category.

    Payload is small because future_count is bounded by the number of installment
    schedules a user has — typically a few hundred rows at most. No pagination.
    """
    resolver = CategoryResolver(session)
    today = date.today()
    future_txs = session.exec(
        select(Transaction)
        .where(Transaction.date > today)
        .order_by(Transaction.date)
    ).all()

    # month -> category_id -> list[Transaction]
    by_month_cat: Dict[str, Dict[int, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    category_info_by_id: Dict[int, Category] = {}
    for tx in future_txs:
        month = tx.date.strftime("%Y-%m")
        cat = resolver.resolve(tx.category)
        by_month_cat[month][cat.id].append(tx)
        category_info_by_id[cat.id] = cat

    months_out = []
    for month in sorted(by_month_cat.keys()):
        cat_groups = by_month_cat[month]
        categories_out = []
        month_total = Decimal("0")
        month_count = 0

        for cat_id, txs in cat_groups.items():
            cat = category_info_by_id[cat_id]
            cat_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
            month_total += cat_total
            month_count += len(txs)
            categories_out.append(
                {
                    "id": cat.id,
                    "name": cat.name,
                    "color": cat.color,
                    "total": float(cat_total),
                    "count": len(txs),
                    "transactions": [
                        {
                            "id": tx.id,
                            "date": tx.date.isoformat(),
                            "amount": float(abs(tx.amount)),
                            "description": tx.description,
                            "pluggy_category": tx.category,
                        }
                        for tx in txs
                    ],
                }
            )

        categories_out.sort(key=lambda c: c["total"], reverse=True)
        months_out.append(
            {
                "month": month,
                "total": float(month_total),
                "count": month_count,
                "categories": categories_out,
            }
        )

    return {"total_count": len(future_txs), "months": months_out}


@app.get("/stats/monthly")
def stats_monthly(session: Session = Depends(get_session)):
    """Category × month breakdown. Useful for a per-category history view."""
    resolver = CategoryResolver(session)
    today = date.today()
    transactions = session.exec(select(Transaction)).all()
    past_transactions = [tx for tx in transactions if tx.date <= today]

    # (category_id, month) -> total
    matrix: Dict[int, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    counts: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category_info_by_id: Dict[int, Category] = {}
    months_set: set = set()

    for tx in past_transactions:
        cat = resolver.resolve(tx.category)
        month = tx.date.strftime("%Y-%m")
        matrix[cat.id][month] += abs(tx.amount)
        counts[cat.id][month] += 1
        category_info_by_id[cat.id] = cat
        months_set.add(month)

    months = sorted(months_set)

    categories = []
    for cat_id, by_month in matrix.items():
        cat = category_info_by_id[cat_id]
        category_total = sum(by_month.values())
        categories.append(
            {
                "id": cat.id,
                "name": cat.name,
                "color": cat.color,
                "sort_order": cat.sort_order,
                "total": float(category_total),
                "by_month": {m: float(by_month.get(m, Decimal("0"))) for m in months},
                "counts_by_month": {m: counts[cat_id].get(m, 0) for m in months},
            }
        )

    categories.sort(key=lambda c: c["total"], reverse=True)

    return {"months": months, "categories": categories}


@app.get("/stats")
def stats(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    today = date.today()
    effective_to = to_date if to_date is not None else today

    query = select(Transaction)
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    query = query.where(Transaction.date <= effective_to)
    past_transactions = session.exec(query).all()

    # Future-count is only meaningful when the caller didn't constrain the
    # upper bound; otherwise the "future" relative to today is irrelevant
    # to what they asked for.
    future_count = 0
    if to_date is None:
        future_count = len(
            session.exec(
                select(Transaction).where(Transaction.date > today)
            ).all()
        )

    totals_by_category_id: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    counts_by_category_id: Dict[int, int] = defaultdict(int)
    category_info_by_id: Dict[int, Category] = {}
    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spent = Decimal("0")

    for tx in past_transactions:
        # Pluggy returns negative amounts for outflows on credit card statements;
        # treat the absolute value as the spend.
        amount = abs(tx.amount)
        cat = resolver.resolve(tx.category)
        totals_by_category_id[cat.id] += amount
        counts_by_category_id[cat.id] += 1
        category_info_by_id[cat.id] = cat
        totals_by_month[tx.date.strftime("%Y-%m")] += amount
        total_spent += amount

    categories = sorted(
        [
            {
                "id": cat_id,
                "name": category_info_by_id[cat_id].name,
                "color": category_info_by_id[cat_id].color,
                "sort_order": category_info_by_id[cat_id].sort_order,
                "total": float(total),
                "count": counts_by_category_id[cat_id],
            }
            for cat_id, total in totals_by_category_id.items()
        ],
        key=lambda c: c["total"],
        reverse=True,
    )
    months = [
        {"month": month, "total": float(total)}
        for month, total in sorted(totals_by_month.items())
    ]

    return {
        "total_spent": float(total_spent),
        "transaction_count": len(past_transactions),
        "future_transaction_count": future_count,
        "categories": categories,
        "months": months,
    }
