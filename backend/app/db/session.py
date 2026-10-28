from collections.abc import Generator
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the DB engine only when the process actually needs PostgreSQL."""
    settings = get_settings()
    connect_args = {"connect_timeout": 5} if settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")) else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=1800)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session)


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()
        get_session_factory.cache_clear()


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
