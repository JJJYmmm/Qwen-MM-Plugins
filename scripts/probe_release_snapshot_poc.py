#!/usr/bin/env python3
"""Run inside an isolated installed distribution, without calling external tools/services."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from importlib import metadata

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from packaging.version import Version

import mcp_framework


async def probe(package: str) -> list[str]:
    params = StdioServerParameters(command=sys.executable, args=["-m", package])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return [tool.name for tool in (await session.list_tools()).tools]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--plugin-version", required=True)
    parser.add_argument("--distribution-version", required=True)
    parser.add_argument("--dependency-fragment")
    parser.add_argument("--marker", action="store_true")
    args = parser.parse_args()
    package = "qwen_mm_plugins_" + args.capability.replace("-", "_")
    module = importlib.import_module(package)
    assert module.__version__ == args.plugin_version
    assert mcp_framework.__version__ == args.distribution_version
    assert Version(metadata.version("qwen-mm-plugins")) == Version(args.distribution_version)
    requirements = metadata.requires("qwen-mm-plugins") or []
    if args.dependency_fragment:
        assert any(args.dependency_fragment in item for item in requirements), requirements
    if args.marker:
        assert importlib.import_module(package + ".poc_marker").VALUE == "newer-developer-code"
    else:
        assert importlib.util.find_spec("qwen_mm_plugins_mhs.poc_marker") is None
    tools = asyncio.run(probe(package))
    assert tools
    installed = {}
    for dependency in ("mcp", "pydantic", "anyio", "openai", "pillow", "requests", "msgpack"):
        try:
            installed[dependency] = metadata.version(dependency)
        except metadata.PackageNotFoundError:
            pass
    print(
        json.dumps(
            {
                "capability": args.capability,
                "plugin_version": module.__version__,
                "distribution_version": metadata.version("qwen-mm-plugins"),
                "framework_version": mcp_framework.__version__,
                "tool_count": len(tools),
                "tools": tools,
                "installed_dependencies": installed,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
