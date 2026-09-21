from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from assure_control_api.models import Base
from assure_control_api.rls import set_auth_lookup


def database_url() -> str:
    return os.environ.get("ASSURE_DATABASE_URL", "sqlite://")


def make_engine(url: str | None = None):
    url = url or database_url()
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def session_dep(factory: sessionmaker[Session]):
    def _dep() -> Generator[Session, None, None]:
        session = factory()
        try:
            set_auth_lookup(session, True)
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _dep
