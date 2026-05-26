from pathlib import Path

from sqlmodel import Session, create_engine

from app.config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    # Apply any pending Alembic migrations. Schema is owned by alembic/versions,
    # not by SQLModel.metadata.create_all anymore.
    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def get_session():
    with Session(engine) as session:
        yield session
