"""MCP tool: press a key or modified key against the current app snapshot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from qwen_mm_plugins_cua.tools._actions import DeliveredActionArgs, execute


class PressKeyArgs(DeliveredActionArgs):
    key: str = Field(min_length=1, description="Key name such as return, tab, escape, down, or a letter.")
    modifiers: list[str] | None = Field(default=None, description="Optional cmd/shift/option/ctrl/fn modifiers.")
    repeat: int = Field(default=1, ge=1, le=50, description="Number of key presses.")
    element_token: str | None = Field(default=None, description="Optional exact element to focus first.")
    coordinate_space: Literal["pixel", "relative_1000"] = Field(
        default="pixel", description="Coordinate convention for optional x/y focus point."
    )
    x: float | None = Field(default=None, description="Optional focus X.")
    y: float | None = Field(default=None, description="Optional focus Y.")

    @model_validator(mode="after")
    def validate_target(self):
        if self.element_token and (self.x is not None or self.y is not None):
            raise ValueError("use element_token or x/y, not both")
        if (self.x is None) != (self.y is None):
            raise ValueError("x and y must be supplied together")
        return self


TOOL: dict[str, Any] = {
    "name": "press_key",
    "description": (
        "Press one key, optionally with modifiers or repetition, against the current snapshot and return fresh "
        "state. Use modifiers for hotkeys instead of a separate hotkey tool."
    ),
    "args": PressKeyArgs,
}


def handle(arguments: dict[str, Any]) -> list[dict[str, str]]:
    return execute("press_key", arguments)
