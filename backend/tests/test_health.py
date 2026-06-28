from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_project_stub_returns_501():
    r = client.post("/api/projects", json={"title": "Test"})
    assert r.status_code == 501  # stub until task B2
