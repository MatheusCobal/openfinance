from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

from app.config import database_settings
from app.services.database_backup import backup_sqlite_database, sqlite_database_path

ALEMBIC_BASE_REVISION = "1ca8aba92fd3"
_startup_backup_done = False


def _connect_args_for_database_url(database_url: str) -> dict:
    if make_url(database_url).get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    return {}


engine = create_engine(
    database_settings.database_url,
    echo=False,
    connect_args=_connect_args_for_database_url(database_settings.database_url),
)


def _alembic_config() -> Config:
    project_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_settings.database_url)
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


def _backup_before_migrations_once() -> None:
    global _startup_backup_done
    if _startup_backup_done:
        return
    database_path = sqlite_database_path(database_settings.database_url)
    if database_path is None or not database_path.exists():
        _startup_backup_done = True
        return
    backup_sqlite_database(database_settings.database_url, "alembic-upgrade")
    _startup_backup_done = True


def init_db() -> None:
    # Apply any pending Alembic migrations. Existing pre-Alembic databases are
    # stamped after receiving the columns introduced with the baseline revision.
    cfg = _alembic_config()
    _backup_before_migrations_once()
    _prepare_legacy_database_for_alembic(cfg)
    command.upgrade(cfg, "head")


def get_session():
    with Session(engine) as session:
        yield session
