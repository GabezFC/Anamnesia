"""Smoke test: spawn the MCP server over stdio with the official client, list tools, call memory_search."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def main(query: str):
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"], cwd=str(ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", sorted(t.name for t in tools.tools))
            res = await s.call_tool("memory_search", {"query": query, "pipeline": "graphify_jev", "max_results": 5})
            payload = res.structured_content or json.loads(res.content[0].text)
            print(json.dumps({k: payload[k] for k in ("pipeline", "sources", "metrics")}, ensure_ascii=False, indent=1)[:1500])
            print("context chars:", len(payload["context"]))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Qual driver do Postgres o Norteia usa?"))
