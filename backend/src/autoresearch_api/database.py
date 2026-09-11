from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def ensure_schema(bind=engine) -> None:
    """Create missing tables and add new nullable columns for existing SQLite DBs."""
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    alterations = {
        "workflows": [("project_id", "VARCHAR(36)")],
        "runs": [("project_id", "VARCHAR(36)")],
        "metrics": [("project_id", "VARCHAR(36)")],
        "projects": [("preferred_base_commit", "VARCHAR(64)")],
    }
    with bind.begin() as connection:
        for table_name, columns in alterations.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns:
                if column_name in existing:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                )
