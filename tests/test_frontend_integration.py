"""Integration tests connecting the frontend SPA and the backend API.

Tests the full integration between the FastAPI backend and the web frontend:
- Static asset and HTML5 SPA route serving (with SPA history fallback).
- API route priority over SPA catch-all (preventing API 404s from returning HTML).
- Search API contract matching web frontend search queries.
- Presence heartbeat API contract matching web frontend check-in.
- Workspace provisioning and lifecycle API contracts matching WorkspaceSwitcher.
"""

from pathlib import Path

import pytest
from app.main import get_frontend_dist, set_frontend_dist
from httpx import AsyncClient


@pytest.fixture
def ensure_frontend_dist():
    """Ensure a valid dist directory exists for tests, creating a fixture if needed."""
    original = get_frontend_dist()
    real_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if real_dist.exists() and (real_dist / "index.html").is_file():
        set_frontend_dist(real_dist)
        yield real_dist
    else:
        # Create a mock dist structure in tmp for headless/isolated environments
        import tempfile

        tmp_dir = tempfile.TemporaryDirectory()
        dist_path = Path(tmp_dir.name)
        (dist_path / "index.html").write_text(
            "<!doctype html><html><head><title>erid.</title></head><body><div id='root'></div></body></html>"
        )
        assets_dir = dist_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "test-bundle.js").write_text("console.log('erid bundle');")
        (assets_dir / "test-bundle.css").write_text("body { background: #fbf9f2; }")
        set_frontend_dist(dist_path)
        yield dist_path
        tmp_dir.cleanup()
    set_frontend_dist(original)


async def test_serve_frontend_index_html(client: AsyncClient, ensure_frontend_dist):
    """GET / serves index.html with 200 OK and HTML content type."""
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()


async def test_serve_spa_client_routes(client: AsyncClient, ensure_frontend_dist):
    """Client-side SPA routes (/continuous-context, /field-guide, /workspace) serve index.html."""
    for path in ["/continuous-context", "/field-guide", "/workspace"]:
        r = await client.get(path)
        assert r.status_code == 200, f"Route {path} failed with status {r.status_code}"
        assert "text/html" in r.headers.get("content-type", "")
        assert "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()


async def test_serve_frontend_static_assets(client: AsyncClient, ensure_frontend_dist):
    """GET /assets/<filename> serves bundled JS and CSS assets."""
    dist = ensure_frontend_dist
    assets = list((dist / "assets").glob("*"))
    assert len(assets) > 0, "No assets found in assets directory"

    first_asset = assets[0]
    r = await client.get(f"/assets/{first_asset.name}")
    assert r.status_code == 200
    assert len(r.content) > 0

    # Non-existent asset must return 404 JSON, not SPA index.html
    r_missing = await client.get("/assets/nonexistent-file.js")
    assert r_missing.status_code == 404
    assert r_missing.json() == {"detail": "Asset Not Found"}

    # Path traversal attempts in /assets must return 404 and not serve files outside dist/assets
    r_traversal = await client.get("/assets/%2e%2e/%2e%2e/pyproject.toml")
    assert r_traversal.status_code == 404
    assert r_traversal.json() == {"detail": "Asset Not Found"}


async def test_spa_path_traversal_blocked(client: AsyncClient, ensure_frontend_dist):
    """Path traversal attempts via SPA route must return 404 and not serve host files."""
    r = await client.get("/%2e%2e/%2e%2e/pyproject.toml")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


async def test_api_routes_priority_over_spa(client: AsyncClient, ensure_frontend_dist):
    """API endpoints are matched before the SPA fallback."""
    # Real API route returns JSON
    r_workspaces = await client.get("/api/workspaces")
    assert r_workspaces.status_code == 200
    assert isinstance(r_workspaces.json(), list)

    # Health check returns JSON
    r_health = await client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json() == {"status": "ok"}

    # Unknown /api route returns 404 JSON, NOT HTML
    r_api_404 = await client.get("/api/nonexistent-route-endpoint")
    assert r_api_404.status_code == 404
    assert r_api_404.json() == {"detail": "Not Found"}
    assert "text/html" not in r_api_404.headers.get("content-type", "")


async def test_api_frontend_search_contract(client: AsyncClient, authed):
    """Backend /search endpoint responds to queries matching frontend client requests."""
    slug, headers = authed

    # Create a task and a decision to search for
    t_resp = await client.post(
        f"/api/workspaces/{slug}/tasks",
        headers=headers,
        json={"title": "Implement Redis PubSub pipeline", "status": "in_progress"},
    )
    assert t_resp.status_code == 201

    d_resp = await client.post(
        f"/api/workspaces/{slug}/decisions",
        headers=headers,
        json={"title": "Adopt Nordic Editorial UI", "reason": "Reduces operator cognitive fatigue"},
    )
    assert d_resp.status_code == 201

    # Search for 'Redis'
    s1 = await client.get(f"/api/workspaces/{slug}/search?q=Redis", headers=headers)
    assert s1.status_code == 200
    data1 = s1.json()
    assert data1["query"] == "Redis"
    assert any("Redis" in t["title"] for t in data1["tasks"])

    # Search for 'Nordic'
    s2 = await client.get(f"/api/workspaces/{slug}/search?q=Nordic", headers=headers)
    assert s2.status_code == 200
    data2 = s2.json()
    assert any("Nordic" in d["title"] for d in data2["decisions"])


async def test_api_frontend_presence_contract(client: AsyncClient, authed):
    """Backend /presence endpoint processes heartbeat payloads sent by frontend Presence."""
    slug, headers = authed

    presence_payload = {
        "actor_name": "Web Architect",
        "actor_type": "human",
        "current_task": "Refactoring context pipeline",
        "current_file": "web/src/pages/LiveWorkspace.jsx",
    }

    # Heartbeat check-in
    post_resp = await client.post(f"/api/workspaces/{slug}/presence", headers=headers, json=presence_payload)
    assert post_resp.status_code == 200
    body = post_resp.json()
    assert body["actor_name"] == "Web Architect"
    assert body["actor_type"] == "human"
    assert body["current_task"] == "Refactoring context pipeline"
    assert body["current_file"] == "web/src/pages/LiveWorkspace.jsx"

    # List presence
    get_resp = await client.get(f"/api/workspaces/{slug}/presence", headers=headers)
    assert get_resp.status_code == 200
    presences = get_resp.json()
    assert any(p["actor_name"] == "Web Architect" for p in presences)


async def test_api_frontend_workspace_provisioning_and_deletion(client: AsyncClient):
    """Backend /workspaces endpoint provisions and deletes workspaces per WorkspaceSwitcher actions."""
    test_slug = "e2e-frontend-ws-test"

    # 1. Provision
    r_prov = await client.post("/api/workspaces", params={"slug": test_slug})
    assert r_prov.status_code == 201
    data = r_prov.json()
    assert data["slug"] == test_slug
    assert data["api_key"] is not None
    api_key = data["api_key"]

    # 2. Verify listed
    r_list = await client.get("/api/workspaces")
    assert r_list.status_code == 200
    slugs = [w["slug"] for w in r_list.json()]
    assert test_slug in slugs

    # 3. Delete from server as owner
    r_del = await client.delete(f"/api/workspaces/{test_slug}", headers={"X-API-Key": api_key})
    assert r_del.status_code == 204

    # 4. Verify no longer listed
    r_list2 = await client.get("/api/workspaces")
    slugs2 = [w["slug"] for w in r_list2.json()]
    assert test_slug not in slugs2


async def test_frontend_dist_fallback_when_dist_missing(client: AsyncClient):
    """When frontend assets are not built, root / returns informative JSON instead of crashing."""
    original = get_frontend_dist()
    import tempfile

    with tempfile.TemporaryDirectory() as empty_dir:
        set_frontend_dist(Path(empty_dir))  # Directory without index.html
        r = await client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "running"
        assert "npm run build" in r.json()["message"]

        # Client route returns 404 when index.html is absent
        r_spa = await client.get("/continuous-context")
        assert r_spa.status_code == 404

    set_frontend_dist(original)
