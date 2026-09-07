from __future__ import annotations

import threading
from pathlib import Path

from alembic.config import Config

from alembic import command

_migration_lock = threading.Lock()
_migrated_databases: set[str] = set()


def is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgres://", "postgresql://"))


def sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def require_postgres_url(database_url: str) -> None:
    if not is_postgres_url(database_url):
        raise ValueError("DATABASE_URL must use PostgreSQL")


def read_migration(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "supabase" / "migrations" / name).read_text(encoding="utf-8")


def run_migrations(database_url: str) -> None:
    root = Path(__file__).resolve().parents[3]
    with _migration_lock:
        if database_url in _migrated_databases:
            return
        require_postgres_url(database_url)
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", sqlalchemy_url(database_url))
        command.upgrade(config, "head")
        _migrated_databases.add(database_url)
