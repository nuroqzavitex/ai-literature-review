from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.services.repositories.database import require_postgres_url, sqlalchemy_url


@lru_cache
def get_engine(database_url: str) -> Engine:
    require_postgres_url(database_url)
    return create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(database_url),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


class SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def execute(self, statement: object, parameters: object | None = None):
        if isinstance(statement, str):
            if parameters is None:
                return self._session.connection().exec_driver_sql(statement)
            return self._session.connection().exec_driver_sql(statement, parameters)
        if parameters is None:
            return self._session.execute(statement)
        return self._session.execute(statement, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._session, name)


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    session = get_session_factory(database_url)()
    proxy = SessionProxy(session)
    try:
        yield proxy
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
