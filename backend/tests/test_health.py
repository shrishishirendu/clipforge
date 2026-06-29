from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_start_stub_still_501_until_b4():
    """Sanity: endpoints not yet built remain explicit 501 stubs."""
    r = client.post("/api/projects/any-id/start")
    assert r.status_code == 501
