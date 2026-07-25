import pytest
from httpx import AsyncClient
from api.app.main import app

@pytest.mark.asyncio
async def test_workspace_summary():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/workspaces/test/summary")
        assert resp.status_code in (200, 404)
