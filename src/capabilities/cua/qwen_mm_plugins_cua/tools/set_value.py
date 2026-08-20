"""MCP tool: set one accessibility element's native value."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from qwen_mm_plugins_cua.tools._actions import SnapshotActionArgs, execute


class SetValueArgs(SnapshotActionArgs):
    element_token: str = Field(description="Exact editable/value element handle from the current state.")
    value: str = Field(description="New native accessibility value.")


TOOL: dict[str, Any] = {
    "name": "set_value",
    "description": (
        "Set an exact element's native accessibility value, then return fresh state. Use for native fields, "
        "sliders, steppers, and popup selections; prefer type_text for free-form web input."
    ),
    "args": SetValueArgs,
}


def handle(arguments: dict[str, Any]) -> list[dict[str, str]]:
    return execute("set_value", arguments)
