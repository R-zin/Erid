from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-context-hub")


@mcp.tool()
async def workspace_summary(slug: str) -> str:
    """Get a shared workspace summary."""
    from .client import APIClient
    client = APIClient()
    data = await client.workspace_summary(slug)
    return str(data)


@mcp.tool()
async def search_context(slug: str, q: str) -> str:
    """Search decisions and tasks in a workspace."""
    from .client import APIClient
    client = APIClient()
    data = await client.search_context(slug, q)
    return str(data)


if __name__ == "__main__":
    mcp.run(transport="stdio")
