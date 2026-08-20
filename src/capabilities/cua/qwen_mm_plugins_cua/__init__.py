"""Qwen-MM-Plugins CUA — a narrow, verified tool surface over Cua Driver."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_framework import build_registry

__version__ = "2.0.1"

SPECS, get_handler, list_tools = build_registry(__name__, ["tools"])

_DRIVER_TOOLS = ["cua-driver"]
if sys.platform == "darwin":
    _DRIVER_TOOLS.extend(
        [
            str(Path.home() / ".local" / "bin" / "cua-driver"),
            "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
        ]
    )

SYSTEM_DEPS = [
    {
        "label": "Cua Driver 0.20.0+",
        "tools": _DRIVER_TOOLS,
        "hint": '/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"',
    }
]

SYSTEM_DEPS_NOTE = (
    "The adapter exposes nine action-specific tools; it does not install or expose Cua Driver's "
    "optional Skill pack or full MCP tool roster. On macOS, verify Accessibility and Screen Recording "
    "with `cua-driver permissions status`."
)

USAGE_NOTE = (
    "Requires Cua Driver 0.20.0 or newer. The runtime is resolved from "
    "QWEN_MM_CUA_DRIVER_PATH, PATH, ~/.local/bin/cua-driver, then the macOS app bundle. "
    "Install from https://cua.ai/driver/install.sh and see the bundled Skill for the snapshot loop."
)
