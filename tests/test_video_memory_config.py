"""Configuration regressions for the standalone video-memory builder."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BUILD_DIR = Path(__file__).resolve().parents[1] / "src/capabilities/video-memory/skill/script/build_memory"


@pytest.mark.parametrize("source", ["environment", "config"])
@pytest.mark.parametrize(
    "value,expected,warns",
    [
        (None, 7200, False),
        ("", 7200, False),
        ("   ", 7200, False),
        ("invalid", 7200, True),
        ("1.5", 7200, True),
        ("15 MiB", 7200, True),
        ("3600", 3600, False),
        (" 9000 ", 9000, False),
    ],
)
def test_builder_import_tolerates_url_expiry(tmp_path, source, value, expected, warns):
    config = tmp_path / "config"
    config.write_text(f"OSS_URL_EXPIRY={value}\n" if source == "config" and value is not None else "")
    env = {k: v for k, v in os.environ.items() if k not in {"OSS_URL_EXPIRY", "PYTHONPATH"}}
    env["QWEN_MM_CONFIG"] = str(config)
    if source == "environment" and value is not None:
        env["OSS_URL_EXPIRY"] = value

    result = subprocess.run(
        [sys.executable, "-c", "import build_graph; print(build_graph.URL_EXPIRY)"],
        cwd=_BUILD_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    assert result.stdout.strip() == str(expected)
    assert ("invalid OSS_URL_EXPIRY=" in result.stderr) is warns
