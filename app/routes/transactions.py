import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.database import get_session
from app.models import Category, Transaction
from app.services.transactions import (
    SPENDING_ACCOUNT_TYPES,
    TRACKED_ACCOUNT_TYPES,
    account_ids_by_type,
    filter_ignored_transactions,
    filter_transactions_by_account_type,
    ignored_description_patterns,
    is_ignored_transaction,
)

router = APIRouter()


@router.get("/transactions")
def list_transactions(
    account_id: Optional[str] = None,
    account_type: Optional[str] = "CREDIT",
    category_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    query = select(Transaction).order_by(Transaction.date.desc())
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if account_type is not None and account_type.upper() != "ALL":
        account_type = account_type.upper()
        if account_type not in TRACKED_ACCOUNT_TYPES:
            raise HTTPException(400, "account_type must be CREDIT, BANK or ALL")
        account_ids = account_ids_by_type(session, {account_type})
        if not account_ids:
            return []
        query = query.where(Transaction.account_id.in_(account_ids))
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.date <= to_date)
    if not include_future and to_date is None:
        query = query.where(Transaction.date <= date.today())
    transactions = session.exec(query).all()
    ignored_patterns = ignored_description_patterns(session)
    if not include_ignored and ignored_patterns:
        transactions = [
            tx
            for tx in transactions
            if not is_ignored_transaction(tx, ignored_patterns)
        ]

    def to_dict(tx: Transaction) -> Dict[str, Any]:
        cat = resolver.resolve(tx.category, tx.description)
        return {
            **tx.model_dump(mode="json"),
            "custom_category_id": cat.id,
            "custom_category_name": cat.name,
            "custom_category_color": cat.color,
            "ignored": is_ignored_transaction(tx, ignored_patterns),
        }

    rows = [to_dict(tx) for tx in transactions]
    if category_id is not None:
        rows = [r for r in rows if r["custom_category_id"] == category_id]
    return rows


@router.get("/categories")
def list_categories(session: Session = Depends(get_session)):
    return CategoryResolver(session).all_categories()


@router.get("/export/transactions.csv")
def export_transactions_csv(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    query = select(Transaction).order_by(Transaction.date.desc())
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.date <= to_date)
    if not include_future and to_date is None:
        query = query.where(Transaction.date <= date.today())
    ignored_patterns = ignored_description_patterns(session)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "date",
                "description",
                "amount_original",
                "amount_abs",
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

        for tx in session.exec(query):
            if (
                not include_ignored
                and ignored_patterns
                and is_ignored_transaction(tx, ignored_patterns)
            ):
                continue
            cat = resolver.resolve(tx.category, tx.description)
            writer.writerow(
                [
                    tx.date.isoformat(),
                    tx.description,
                    f"{tx.amount:.2f}",
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


@router.get("/upcoming")
def upcoming(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    today = date.today()
    future_txs = session.exec(
        select(Transaction)
        .where(Transaction.date > today)
        .order_by(Transaction.date)
    ).all()
    future_txs = filter_transactions_by_account_type(
        future_txs,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    future_txs = filter_ignored_transactions(
        future_txs,
        session,
        include_ignored,
    )

    by_month_cat: Dict[str, Dict[int, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    category_info_by_id: Dict[int, Category] = {}
    for tx in future_txs:
        month = tx.date.strftime("%Y-%m")
        cat = resolver.resolve(tx.category, tx.description)
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


@router.get("/stats/monthly")
def stats_monthly(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    resolver = CategoryResolver(session)
    today = date.today()
    transactions = session.exec(select(Transaction)).all()
    past_transactions = [tx for tx in transactions if tx.date <= today]
    past_transactions = filter_transactions_by_account_type(
        past_transactions,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    past_transactions = filter_ignored_transactions(
        past_transactions,
        session,
        include_ignored,
    )

    matrix: Dict[int, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    counts: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category_info_by_id: Dict[int, Category] = {}
    months_set: set = set()

    for tx in past_transactions:
        cat = resolver.resolve(tx.category, tx.description)
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


@router.get("/stats")
def stats(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_ignored: bool = False,
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
    past_transactions = filter_transactions_by_account_type(
        past_transactions,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    past_transactions = filter_ignored_transactions(
        past_transactions,
        session,
        include_ignored,
    )

    future_count = 0
    if to_date is None:
        future_transactions = session.exec(
            select(Transaction).where(Transaction.date > today)
        ).all()
        future_transactions = filter_transactions_by_account_type(
            future_transactions,
            session,
            SPENDING_ACCOUNT_TYPES,
        )
        future_count = len(
            filter_ignored_transactions(
                future_transactions,
                session,
                include_ignored,
            )
        )

    totals_by_category_id: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    counts_by_category_id: Dict[int, int] = defaultdict(int)
    category_info_by_id: Dict[int, Category] = {}
    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spent = Decimal("0")

    for tx in past_transactions:
        amount = abs(tx.amount)
        cat = resolver.resolve(tx.category, tx.description)
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
