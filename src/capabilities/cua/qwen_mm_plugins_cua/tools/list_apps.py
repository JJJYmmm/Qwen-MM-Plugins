"""MCP tool: discover installed and running desktop applications."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from qwen_mm_plugins_cua.driver import CuaError, get_client
from qwen_mm_plugins_cua.tools._actions import StrictArgs
from shared.content import text, text_error


class ListAppsArgs(StrictArgs):
    query: str | None = Field(default=None, description="Optional case-insensitive name or bundle-id filter.")
    running_only: bool = Field(default=False, description="Return only currently running applications.")


TOOL: dict[str, Any] = {
    "name": "list_apps",
    "description": "List discoverable desktop applications, optionally filtered by name, bundle id, or running state.",
    "args": ListAppsArgs,
}


def handle(arguments: dict[str, Any]) -> list[dict[str, str]]:
    try:
        result = get_client().call("list_apps")
        apps = result.get("apps")
        if not isinstance(apps, list):
            raise CuaError("cua-driver list_apps returned no apps array")
        query = str(arguments.get("query") or "").strip().casefold()
        if query:
            apps = [
                app
                for app in apps
                if query in str(app.get("name") or "").casefold() or query in str(app.get("bundle_id") or "").casefold()
            ]
        if arguments.get("running_only", False):
            apps = [app for app in apps if app.get("running") is True]
        return [text(json.dumps({"ok": True, "count": len(apps), "apps": apps}, ensure_ascii=False, indent=2))]
    except (CuaError, ValueError) as exc:
        return text_error(str(exc))
