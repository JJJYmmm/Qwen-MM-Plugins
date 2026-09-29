from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from scripts import release_snapshot_poc as poc

ROOT = Path(REPO_ROOT)
URL = "https://github.com/QwenLM/Qwen-MM-Plugins.git"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "source"
    # CI may checkout only one commit. Use its tree as a fresh fixture, so the bare test remote
    # receives a complete history without fetching any network objects or weakening Git checks.
    repo.mkdir()
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(repo)], input=archive, check=True, capture_output=True)
    git(repo, "init", "--quiet", "--initial-branch=main")
    git(repo, "config", "user.name", "Release Test")
    git(repo, "config", "user.email", "release@example.test")
    git(repo, "config", "commit.gpgsign", "false")
    # Include work-in-progress tooling without depending on a committed parent checkout.
    for name in ("prepare_plugin_release.py", "release_snapshot_poc.py"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    # These are synthetic release scenarios, independent of the real catalog's current version
    # or provenance. Otherwise the next genuine release would invalidate every test's inputs.
    shutil.rmtree(repo / ".release", ignore_errors=True)
    poc.prepare(repo, {"search": "1.1.0", "mhs": "1.1.0", "edu-agent": "1.1.0"}, "1.1.9", URL)
    (repo / "src/capabilities/mhs/qwen_mm_plugins_mhs/poc_marker.py").unlink(missing_ok=True)
    project = repo / "pyproject.toml"
    project.write_text(
        re.sub(r"^mhs\s*=\s*\[[^\n]*\]", 'mhs = ["msgpack>=1.1,<2"]', project.read_text(), count=1, flags=re.MULTILINE),
        encoding="utf-8",
    )
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "test: source fixture with snapshot tooling")
    return repo


def edit(repo: Path, path: str, text: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "test: advance developer code without releasing")
    return git(repo, "rev-parse", "HEAD")


def servers(repo: Path) -> set[str]:
    return {
        cap
        for cap in poc.read_json(repo / "plugin-versions.json")["plugins"]
        if (repo / f"src/capabilities/{cap}/.mcp.json").exists()
    }


@pytest.mark.parametrize(
    "kind",
    [
        "capability",
        "skill",
        "shared",
        "framework",
        "base-dependency",
        "extra",
        "transitive-extra",
        "version-stamp",
        "docs",
    ],
)
def test_plan_classifies_runtime_and_dependency_scope(checkout, kind):
    repo = checkout
    base = git(repo, "rev-parse", "HEAD")
    project = (repo / "pyproject.toml").read_text()
    expected = set()
    if kind == "capability":
        edit(repo, "src/capabilities/search/qwen_mm_plugins_search/poc_marker.py", "VALUE = 1\n")
        expected = {"search"}
    elif kind == "skill":
        edit(repo, "src/capabilities/edu-agent/skill/poc.md", "New Skill behavior\n")
        expected = {"edu-agent"}
    elif kind == "shared":
        edit(repo, "src/shared/poc_marker.py", "VALUE = 1\n")
        expected = servers(repo)
    elif kind == "framework":
        path = "src/mcp_framework.py"
        edit(repo, path, (repo / path).read_text() + "\nPOC_FRAMEWORK_VALUE = 1\n")
        expected = servers(repo)
    elif kind == "base-dependency":
        edit(repo, "pyproject.toml", project.replace('"pillow<12"', '"pillow<11"'))
        expected = servers(repo)
    elif kind == "extra":
        edit(repo, "pyproject.toml", project.replace('search = ["requests[socks]"]', 'search = ["requests[socks]<3"]'))
        expected = {"search"}
    elif kind == "transitive-extra":
        edit(repo, "pyproject.toml", project.replace('"resvg-py"', '"resvg-py>=0.2"'))
        expected = {"core"}
    elif kind == "version-stamp":
        path = "src/capabilities/search/qwen_mm_plugins_search/__init__.py"
        edit(repo, path, re.sub(r'__version__ = "[^"]+"', '__version__ = "9.0.0"', (repo / path).read_text()))
    else:
        edit(repo, "docs/en/poc.md", "Guide change\n")
    result = poc.plan(repo, base, "HEAD")
    assert set(result["affected"]) == expected
    assert "edu-agent" not in result["affected"] or kind == "skill"


def test_two_phase_publish_preserves_newer_code_and_tracks_each_runtime(checkout, tmp_path):
    repo = checkout
    base = git(repo, "rev-parse", "HEAD")
    original_index = (repo / "plugin-versions.json").read_bytes()
    remote = tmp_path / "remote.git"
    git(repo, "init", "--bare", str(remote))
    a = tmp_path / "snapshot-a"
    info_a = poc.snapshot(repo, base, {"search": "1.1.1-rc.poc.1"}, "1.1.10-rc.poc.1", URL, a)
    assert (repo / "plugin-versions.json").read_bytes() == original_index
    assert git(repo, "rev-parse", "HEAD") == base
    repeated = poc.snapshot(
        repo, base, {"search": "1.1.1-rc.poc.1"}, "1.1.10-rc.poc.1", URL, tmp_path / "snapshot-retry"
    )
    assert repeated["release_commit"] == info_a["release_commit"]
    with pytest.raises(RuntimeError, match="catalog promotion refused"):
        poc.promote(repo, base, a, str(remote), tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()
    poc.publish(a, str(remote))
    poc.publish(a, str(remote))  # Publishing is idempotent and does not move tags.

    marker = "src/capabilities/mhs/qwen_mm_plugins_mhs/poc_marker.py"
    source_b = edit(repo, marker, "VALUE = 'newer-developer-code'\n")
    project = (repo / "pyproject.toml").read_text().replace('mhs = ["msgpack>=1.1,<2"]', 'mhs = ["msgpack>=1.1,<1.2"]')
    source_b = edit(repo, "pyproject.toml", project)
    b = tmp_path / "snapshot-b"
    info_b = poc.snapshot(repo, source_b, {"mhs": "1.1.1-rc.poc.2"}, "1.1.11-rc.poc.2", URL, b)
    poc.publish(b, str(remote))
    assert info_a["dependency_sha256"] != info_b["dependency_sha256"]
    assert not (a / marker).exists()
    assert (b / marker).exists()

    catalog_a = tmp_path / "catalog-a"
    poc.promote(repo, source_b, a, str(remote), catalog_a)
    assert (catalog_a / marker).read_text() == "VALUE = 'newer-developer-code'\n"
    assert (catalog_a / "pyproject.toml").read_text() == project
    remaining = poc.plan(catalog_a, base, "HEAD")
    assert set(remaining["affected"]) == {"mhs"}  # Snapshot commit is outside main; source SHA avoids repeats.

    catalog_b = tmp_path / "catalog-b"
    promoted_b = poc.promote(catalog_a, "HEAD", b, str(remote), catalog_b)
    ledger = promoted_b["plugins"]
    assert ledger["search"]["distribution_version"] == "1.1.10-rc.poc.1"
    assert ledger["mhs"]["distribution_version"] == "1.1.11-rc.poc.2"
    assert ledger["search"]["source_commit"] == base
    assert ledger["mhs"]["source_commit"] == source_b
    assert poc.plan(catalog_b, "HEAD", "HEAD")["affected"] == {}
    repeated_promotion = poc.promote(catalog_b, "HEAD", b, str(remote), tmp_path / "catalog-retry")
    assert repeated_promotion["catalog_commit"] == promoted_b["catalog_commit"]
    with pytest.raises(RuntimeError, match="would regress"):
        poc.promote(catalog_b, "HEAD", a, str(remote), tmp_path / "stale-catalog")


def test_conflicting_tag_blocks_publication_and_promotion(checkout, tmp_path):
    repo = checkout
    remote = tmp_path / "remote.git"
    git(repo, "init", "--bare", str(remote))
    target = tmp_path / "snapshot"
    info = poc.snapshot(repo, "HEAD", {"search": "1.1.1-rc.conflict"}, "1.1.10-rc.conflict", URL, target)
    tag = info["plugins"]["search"]["tag"]
    git(repo, "tag", tag)
    git(repo, "push", str(remote), f"refs/tags/{tag}")
    with pytest.raises(RuntimeError, match="must never move"):
        poc.publish(target, str(remote))
    with pytest.raises(RuntimeError, match="catalog promotion refused"):
        poc.promote(repo, "HEAD", target, str(remote), tmp_path / "catalog")


def test_multi_capability_snapshot_shares_one_distribution(checkout, tmp_path):
    repo = checkout
    snapshot = tmp_path / "snapshot"
    info = poc.snapshot(
        repo,
        "HEAD",
        {"search": "1.1.1-rc.multi", "edu-agent": "1.1.1-rc.multi"},
        "1.1.10-rc.multi",
        "https://github.com/JJJYmmm/Qwen-MM-Plugins.git",
        snapshot,
    )
    assert len(info["plugins"]) == 2
    assert not (snapshot / "src/capabilities/edu-agent/.mcp.json").exists()
    args = poc.read_json(snapshot / "src/capabilities/search/.mcp.json")["mcpServers"]["qwen-mm-plugins-search"]["args"]
    assert "github.com/JJJYmmm" in args[args.index("--from") + 1]
    remote = tmp_path / "remote.git"
    git(repo, "init", "--bare", str(remote))
    poc.publish(snapshot, str(remote))
    assert {poc.remote_target(snapshot, str(remote), item["tag"]) for item in info["plugins"].values()} == {
        info["release_commit"]
    }
