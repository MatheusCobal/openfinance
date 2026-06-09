from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

from app.config import settings

ALEMBIC_BASE_REVISION = "1ca8aba92fd3"

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def _alembic_config() -> Config:
    project_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _add_column_if_missing(
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


def _prepare_legacy_database_for_alembic(cfg: Config) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if not table_names or "alembic_version" in table_names:
        return
    legacy_core_tables = {"item", "account", "accountsync", "transaction", "category"}
    if not legacy_core_tables.issubset(table_names):
        return

    _add_column_if_missing("item", "sync_started_at", "sync_started_at DATETIME")
    _add_column_if_missing("item", "sync_finished_at", "sync_finished_at DATETIME")
    _add_column_if_missing("item", "last_sync_error", "last_sync_error VARCHAR")
    _add_column_if_missing("accountsync", "last_error", "last_error VARCHAR")
    _add_column_if_missing("accountsync", "last_error_at", "last_error_at DATETIME")

    command.stamp(cfg, ALEMBIC_BASE_REVISION)


def init_db() -> None:
    # Apply any pending Alembic migrations. Existing pre-Alembic databases are
    # stamped after receiving the columns introduced with the baseline revision.
    cfg = _alembic_config()
    _prepare_legacy_database_for_alembic(cfg)
    command.upgrade(cfg, "head")


def get_session():
    with Session(engine) as session:
        yield session
