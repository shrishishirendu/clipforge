from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_approve_stub_still_501_until_b7():
    """Sanity: endpoints not yet built remain explicit 501 stubs."""
    r = client.post("/api/projects/any-id/approve")
    assert r.status_code == 501
