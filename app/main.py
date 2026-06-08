from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routes import (
    bank,
    budgets,
    credit_card,
    expected_income,
    fixed_costs,
    history,
    pages,
    planning,
    pluggy_webhooks,
    rules,
    sync,
    transactions,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="OpenFinance Collector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(pages.router)
app.include_router(pluggy_webhooks.router)
app.include_router(sync.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(budgets.router)
app.include_router(history.router)
app.include_router(expected_income.router)
app.include_router(fixed_costs.router)
app.include_router(planning.router)
app.include_router(credit_card.router)
app.include_router(bank.router)
