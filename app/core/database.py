from collections.abc import Generator
from math import ceil

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine() -> Engine:
    settings = get_settings()
    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        engine_options.update(
            {
                "pool_timeout": settings.database_pool_timeout_seconds,
                "connect_args": {
                    "connect_timeout": ceil(settings.database_connect_timeout_seconds),
                    "options": (
                        "-c statement_timeout="
                        f"{ceil(settings.database_query_timeout_seconds * 1000)}"
                    ),
                },
            }
        )
    return create_engine(settings.database_url, **engine_options)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
