"""B2: project creation + the two-phase presigned upload flow (FR-01..06)."""
from sqlalchemy.orm import Session

from app.models.entities import AssetStatus, MediaAsset

# One of each asset type, per the requirements (FR-01..03).
ASSETS = [("video", "talk.mp4"), ("deck", "slides.pptx"), ("summary", "notes.docx")]


def test_create_project_returns_id_and_created_status(client):
    r = client.post("/api/projects", json={"title": "My Talk"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    assert body["title"] == "My Talk"
    assert body["status"] == "created"


def test_full_upload_flow_yields_three_ready_assets(client, storage, db_engine):
    """create project, upload three files, see three MediaAssets (BUILD_PLAN B2)."""
    pid = client.post("/api/projects", json={"title": "Talk"}).json()["id"]

    for atype, fname in ASSETS:
        # 1. request a presigned upload slot
        r = client.post(f"/api/projects/{pid}/assets",
                        json={"type": atype, "filename": fname})
        assert r.status_code == 201, r.text
        up = r.json()
        assert up["type"] == atype
        assert up["upload_url"].startswith("https://fake-storage.local/")
        assert up["storage_uri"].startswith(f"projects/{pid}/{atype}/")

        # 2. client PUTs the bytes straight to storage (simulated)
        storage.simulate_upload(up["storage_uri"], size_bytes=2048)

        # 3. asset-complete callback flips PENDING -> READY with the real size
        c = client.post(f"/api/projects/{pid}/assets/{up['asset_id']}/complete")
        assert c.status_code == 200, c.text
        done = c.json()
        assert done["status"] == "ready"
        assert done["size_bytes"] == 2048

    # three MediaAssets persisted, one of each type, all READY
    with Session(db_engine) as s:
        assets = s.query(MediaAsset).filter_by(project_id=pid).all()
        assert len(assets) == 3
        assert {a.type.value for a in assets} == {"video", "deck", "summary"}
        assert all(a.status == AssetStatus.READY for a in assets)


def test_register_asset_rejects_unknown_project(client):
    r = client.post("/api/projects/does-not-exist/assets",
                    json={"type": "video", "filename": "x.mp4"})
    assert r.status_code == 404


def test_register_asset_rejects_invalid_type(client):
    pid = client.post("/api/projects", json={"title": "T"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/assets",
                    json={"type": "audio", "filename": "x.mp3"})
    assert r.status_code == 422


def test_register_asset_rejects_wrong_extension(client):
    """A deck must be .pptx/.pdf, not .mp4 (FR-02, FR-04)."""
    pid = client.post("/api/projects", json={"title": "T"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/assets",
                    json={"type": "deck", "filename": "slides.mp4"})
    assert r.status_code == 422


def test_complete_before_upload_conflicts(client):
    """Completing before the object exists in storage must fail (no false READY)."""
    pid = client.post("/api/projects", json={"title": "T"}).json()["id"]
    up = client.post(f"/api/projects/{pid}/assets",
                     json={"type": "video", "filename": "talk.mp4"}).json()
    r = client.post(f"/api/projects/{pid}/assets/{up['asset_id']}/complete")
    assert r.status_code == 409


def test_complete_rejects_oversize_upload(client, storage):
    """Oversize files are rejected at the callback against the real size (FR-04)."""
    pid = client.post("/api/projects", json={"title": "T"}).json()["id"]
    up = client.post(f"/api/projects/{pid}/assets",
                     json={"type": "summary", "filename": "notes.txt"}).json()
    storage.simulate_upload(up["storage_uri"], size_bytes=26 * 1024 ** 2)  # > 25 MiB
    r = client.post(f"/api/projects/{pid}/assets/{up['asset_id']}/complete")
    assert r.status_code == 413
