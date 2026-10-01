#!/usr/bin/env python3
"""Portable launcher for the packaged Music2MV pipeline implementation."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
import types
from pathlib import Path


def _check_python_prefix() -> None:
    # Check before importing the pipeline or third-party packages, so a wrong environment
    # produces an actionable error instead of an unrelated missing-dependency traceback.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--expected-python-prefix")
    args, remaining = parser.parse_known_args()
    if args.expected_python_prefix is not None:
        if Path(args.expected_python_prefix).resolve() != Path(sys.prefix).resolve():
            parser.exit(
                2,
                "MCP Python environment mismatch: "
                f"expected {args.expected_python_prefix!r}, running {sys.prefix!r}. "
                "Use python_executable returned by get_music2mv_runtime unchanged.\n",
            )
    sys.argv[1:] = remaining


if __name__ == "__main__":
    _check_python_prefix()

_SCRIPT = Path(__file__).resolve()
_CAPABILITY_DIR = _SCRIPT.parents[5]
_SRC_DIR = _SCRIPT.parents[7]
sys.path.insert(0, str(_CAPABILITY_DIR))
sys.path.insert(0, str(_SRC_DIR))


def _install_portable_env_fallback() -> None:
    """Provide shared.env only when a git-subdir plugin is run outside the wheel environment."""
    try:
        if importlib.util.find_spec("shared.env") is not None:
            return
    except ModuleNotFoundError:
        pass

    spec = importlib.util.spec_from_file_location("shared.env", _SCRIPT.with_name("env_config.py"))
    assert spec is not None and spec.loader is not None
    env_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env_module)

    shared_module = types.ModuleType("shared")
    shared_module.__path__ = []
    sys.modules.setdefault("shared", shared_module)
    sys.modules["shared.env"] = env_module


_install_portable_env_fallback()
main = importlib.import_module("qwen_mm_plugins_omni_chatcut.music_to_mv.pipeline").main


if __name__ == "__main__":
    main()
