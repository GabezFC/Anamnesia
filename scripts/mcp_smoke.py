"""Smoke test: spawn the MCP server over stdio with the official client, list tools, call memory_search.

ANA-082: runs offline and hermetic (CI-safe): bundled synthetic vault, throwaway ANAMNESIA_HOME,
`baseline` pipeline (no paid judge, no graphify binary), MG_MCP_RESPONSE=full so the payload carries
`pipeline`/`sources`/`metrics` (the default `compact` shape only has run_id/context/metrics, which is
what made the old version die with KeyError). Exit 0 = OK, 1 = contract violation, 2 = timeout.

Usage: python scripts/mcp_smoke.py [query] [--timeout 30] [--pipeline baseline]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

DEFAULT_QUERY = "Qual driver do Postgres o Norteia usa?"


def validate(tool_names: list[str], payload: dict) -> list[str]:
    """Contract check; returns a list of problems (empty = OK)."""
    problems: list[str] = []
    if "memory_search" not in tool_names:
        problems.append(f"tool memory_search missing (got {tool_names})")
    for key in ("run_id", "context", "metrics"):
        if key not in payload:
            problems.append(f"payload missing '{key}' (keys: {sorted(payload)})")
    if "context" in payload and not isinstance(payload["context"], str):
        problems.append("context is not a string")
    if "metrics" in payload and not isinstance(payload["metrics"], dict):
        problems.append("metrics is not an object")
    return problems


async def run(query: str, pipeline: str, home: str) -> tuple[list[str], dict]:
    env = {
        "ANAMNESIA_HOME": home,
        "MG_MCP_RESPONSE": "full",
        "MEMORY_GATEWAY_VAULT": str(ROOT / "data" / "synthetic_vault"),
        "PYTHONUNBUFFERED": "1",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            names = sorted(t.name for t in tools.tools)
            res = await s.call_tool("memory_search", {"query": query, "pipeline": pipeline, "max_results": 5})
            payload = res.structured_content or json.loads(res.content[0].text)
            return names, payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--pipeline", default="baseline")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mcp_smoke_") as home:
        try:
            names, payload = asyncio.run(asyncio.wait_for(run(args.query, args.pipeline, home), args.timeout))
        except (asyncio.TimeoutError, TimeoutError):
            print(f"mcp_smoke: TIMEOUT after {args.timeout}s", file=sys.stderr)
            return 2
    problems = validate(names, payload)
    print("tools:", names)
    shown = {k: payload.get(k) for k in ("pipeline", "run_id", "sources", "metrics") if k in payload}
    print(json.dumps(shown, ensure_ascii=False, indent=1, default=str)[:1500])
    print("context chars:", len(payload.get("context", "")), f"| {time.perf_counter() - t0:.1f}s")
    for p in problems:
        print("mcp_smoke: FAIL:", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
