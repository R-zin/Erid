import httpx

API_BASE = "http://localhost:8000"


class APIClient:
    def __init__(self, base_url: str = API_BASE):
        self.base_url = base_url
        self.client = httpx.AsyncClient()

    async def workspace_summary(self, slug: str):
        r = await self.client.get(f"{self.base_url}/api/workspaces/{slug}/summary")
        r.raise_for_status()
        return r.json()

    async def search_context(self, slug: str, q: str):
        r = await self.client.get(f"{self.base_url}/api/workspaces/{slug}/search", params={"q": q})
        r.raise_for_status()
        return r.json()
