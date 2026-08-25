from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def test_serves_dashboard_index_from_configured_dist(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id='root'>dashboard</div>", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/")

    assert response.status_code == 200
    assert "dashboard" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_spa_fallback_does_not_intercept_api(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("dashboard", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True




def test_serves_static_files_from_dist_root_before_spa_fallback(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("dashboard", encoding="utf-8")
    (dist / "bg.mp4").write_bytes(b"video-bytes")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/bg.mp4")

    assert response.status_code == 200
    assert response.content == b"video-bytes"


def test_spa_nested_route_returns_index(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("dashboard nested", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/groups")

    assert response.status_code == 200
    assert "dashboard nested" in response.text
