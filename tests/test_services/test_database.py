from pathlib import Path

from src.services.repositories.database import run_migrations


def test_sqlite_migration_creates_parent_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "litreview.db"

    run_migrations(f"sqlite:///{database_path}")

    assert database_path.exists()
