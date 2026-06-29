"""Test fixtures. Endpoint tests run against an in-memory SQLite DB and a fake
object store, so the suite is hermetic — no Postgres or MinIO required, keeping
`pytest` green anywhere (working agreement)."""
import os

import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import Base
from app.services.storage import get_storage
from app.workers.queue import QUEUE_NAME, get_queue


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

    def download_to_path(self, key: str, dest_path: str) -> None:
        if key not in self.objects:
            raise FileNotFoundError(key)
        # content is irrelevant — fake providers/engine ignore the file
        with open(dest_path, "wb") as fh:
            fh.write(b"fake-media-bytes")

    def upload_file(self, local_path: str, key: str, content_type: str | None = None) -> None:
        self.objects[key] = os.path.getsize(local_path)

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://fake-storage.local/get/{key}?sig=test&ttl={expires_in}"

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
def queue():
    """A fakeredis-backed async queue: enqueue() records jobs without running them,
    so tests can assert what was enqueued without a worker or live Redis."""
    return Queue(QUEUE_NAME, connection=fakeredis.FakeStrictRedis())


@pytest.fixture
def make_project(client, storage):
    """Factory: create a project and complete READY uploads for the given types."""
    names = {"video": "talk.mp4", "deck": "slides.pptx", "summary": "notes.docx"}

    def _make(types=("video", "deck", "summary"), vocabulary=None):
        pid = client.post("/api/projects",
                          json={"title": "T", "vocabulary": vocabulary or []}).json()["id"]
        for t in types:
            up = client.post(f"/api/projects/{pid}/assets",
                             json={"type": t, "filename": names[t]}).json()
            storage.simulate_upload(up["storage_uri"], size_bytes=4096)
            client.post(f"/api/projects/{pid}/assets/{up['asset_id']}/complete")
        return pid

    return _make


@pytest.fixture
def client(db_engine, storage, queue):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
