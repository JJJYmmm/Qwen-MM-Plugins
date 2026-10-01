"""Keep standalone skills and installed servers on the same configuration contract."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.sync_env_readers import mirror_paths, sync

_ROOT = Path(__file__).resolve().parents[1]
_MIRRORS = mirror_paths(_ROOT)
_READERS = [_ROOT / "src/shared/env.py", *_MIRRORS]
_VAR = "QMP_TEST_ENV_MIRROR"


def test_standalone_readers_are_current():
    assert sync(_ROOT) == 0


def test_sync_repairs_only_the_mirrored_region(tmp_path):
    source = tmp_path / "src/shared/env.py"
    mirror = tmp_path / "src/capabilities/example/skill/env_config.py"
    source.parent.mkdir(parents=True)
    mirror.parent.mkdir(parents=True)
    source.write_text((_ROOT / "src/shared/env.py").read_text(encoding="utf-8"), encoding="utf-8")
    original = _MIRRORS[0].read_text(encoding="utf-8") + "\nPLUGIN_SETTING = 'keep'\n"
    mirror.write_text(original.replace("def get_env(", "def stale_get_env("), encoding="utf-8")

    assert sync(tmp_path) == 1
    assert sync(tmp_path, write=True) == 0
    assert mirror.read_text(encoding="utf-8") == original


@pytest.fixture(params=_READERS, ids=lambda p: p.relative_to(_ROOT).parts[2])
def reader(request, tmp_path, monkeypatch):
    monkeypatch.setenv("QWEN_MM_CONFIG", str(tmp_path / "config"))
    monkeypatch.delenv(_VAR, raising=False)
    spec = importlib.util.spec_from_file_location("_test_env_reader", request.param)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._config_cache = None
    return module


def test_reader_parses_config_and_preserves_empty_overrides(reader, tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.write_text(
        f"# comment\nexport {_VAR}='first'\n{_VAR} = \"last=value with spaces\"\nmalformed\n=ignored\n",
        encoding="utf-8",
    )
    assert reader.get_env(_VAR, "default") == "last=value with spaces"
    monkeypatch.setenv(_VAR, "")
    assert reader.get_env(_VAR, "default") == ""
    monkeypatch.delenv(_VAR)
    config.write_text(f"{_VAR}=\n", encoding="utf-8")
    assert reader.get_env(_VAR, "default", refresh_config=True) == ""


def test_reader_refreshes_atomically_replaced_config(reader, tmp_path):
    config = tmp_path / "config"
    replacement = tmp_path / "replacement"
    config.write_text(f"{_VAR}=first\n", encoding="utf-8")
    assert reader.get_env(_VAR) == "first"
    replacement.write_text(f"{_VAR}=second\n", encoding="utf-8")
    replacement.replace(config)
    assert reader.get_env(_VAR) == "first"
    assert reader.get_env(_VAR, refresh_config=True) == "second"


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid_utf8"])
def test_reader_falls_back_for_unreadable_config(reader, tmp_path, kind):
    config = tmp_path / "config"
    if kind == "directory":
        config.mkdir()
    elif kind == "invalid_utf8":
        config.write_bytes(b"\xff")
    assert reader.get_env(_VAR, "default") == "default"


def test_reader_resolves_config_location_precedence(reader, tmp_path, monkeypatch):
    directory = tmp_path / "settings"
    monkeypatch.setenv("QWEN_MM_CONFIG_DIR", str(directory))
    assert reader.config_file() == str(tmp_path / "config")
    monkeypatch.delenv("QWEN_MM_CONFIG")
    assert reader.config_file() == str(directory / "config")
    monkeypatch.delenv("QWEN_MM_CONFIG_DIR")
    assert reader.config_file() == str(Path.home() / ".qwen-mm-plugins/config")


@pytest.mark.parametrize("value,expected", [(" 9876 ", 9876), ("", 9875), ("invalid", 9875), ("15 MiB", 9875)])
def test_reader_plain_integer_fallback(reader, monkeypatch, value, expected):
    monkeypatch.setenv(_VAR, value)
    assert reader.get_int_env(_VAR, 9875) == expected


@pytest.mark.parametrize(
    "value,default,expected", [(" On ", False, True), (" OFF ", True, False), ("maybe", True, True)]
)
def test_reader_boolean_fallback(reader, monkeypatch, value, default, expected):
    monkeypatch.setenv(_VAR, value)
    assert reader.get_bool_env(_VAR, default) is expected


@pytest.mark.parametrize("path", _MIRRORS, ids=lambda p: p.relative_to(_ROOT).parts[2])
def test_standalone_export_contract(path, tmp_path):
    config = tmp_path / "config"
    config.write_text("QMP_TEST_EXPORT=file-value\nQMP_TEST_OVERRIDE=file-value\n", encoding="utf-8")
    env = {**os.environ, "QWEN_MM_CONFIG": str(config), "QMP_TEST_OVERRIDE": ""}
    env.pop("QMP_TEST_EXPORT", None)
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(path)], env=env, capture_output=True, text=True, check=True, timeout=10
    )
    exports = path.relative_to(_ROOT).parts[2] in {"video-memory", "omni-memory"}
    assert result.stdout == ("QMP_TEST_EXPORT=file-value\n" if exports else "")
    assert result.stderr == ""
