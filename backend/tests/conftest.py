"""Test fixtures. Endpoint tests run against an in-memory SQLite DB and a fake
object store, so the suite is hermetic — no Postgres or MinIO required, keeping
`pytest` green anywhere (working agreement)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import Base
from app.services.storage import get_storage


class FakeStorage:
    """In-memory ObjectStorage stand-in. `simulate_upload` mimics the client's
    direct PUT so the complete-callback's stat() check has something to find."""

    def __init__(self):
        self.objects: dict[str, int] = {}  # key -> size_bytes

    def presigned_put_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://fake-storage.local/{key}?sig=test&ttl={expires_in}"

    def stat(self, key: str):
        if key in self.objects:
            return {"size_bytes": self.objects[key]}
        return None

    # --- test helper, not part of the ObjectStorage interface ---
    def simulate_upload(self, key: str, size_bytes: int = 1024):
        self.objects[key] = size_bytes


@pytest.fixture
def db_engine():
    """A fresh in-memory SQLite schema per test (StaticPool keeps one shared conn)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def client(db_engine, storage):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
