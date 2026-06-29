"""SQLAlchemy engine + session factory — the single connection point to Postgres
(architecture §5, data layer). The URL is env-driven via settings so the storage
backend stays swappable; nothing else in the app constructs an engine."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# pool_pre_ping guards against stale connections after the DB restarts (NFR-07).
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
