#!/usr/bin/env python3
"""Prepare one capability release; never commits, tags, or pushes.

Usage:
    python scripts/prepare_plugin_release.py search 1.1.0 --distribution-version 1.0.2

The release bot uses this renderer for both updates and first releases. With --initial, register
an already-implemented plugin in the published index, marketplace, and installer. Multiple
capabilities may share one release commit and distribution version. This only edits metadata;
review the generated version PR and use /publish to create tags before merging its catalog entries.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPS = ROOT / "src" / "capabilities"
INDEX = ROOT / "plugin-versions.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
INSTALLER = ROOT / "install.sh"
FRAMEWORK = ROOT / "src" / "mcp_framework.py"
REPO_URL = "https://github.com/QwenLM/Qwen-MM-Plugins.git"
SEMVER = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\Z")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"{path.relative_to(ROOT)}: expected one match for {pattern!r}, got {count}")
    path.write_text(updated, encoding="utf-8")


def update_installer(cap: str, version: str, *, description: str | None = None, skill_only: bool = False) -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    caps_match = re.search(r"^CAP_ITEMS=\(([^\n]+)\)$", text, re.MULTILINE)
    versions_match = re.search(r"^CAP_VERSIONS=\(([^\n]+)\)$", text, re.MULTILINE)
    if not caps_match or not versions_match:
        raise SystemExit("install.sh: CAP_ITEMS/CAP_VERSIONS must each stay on one line")
    caps = caps_match[1].split()
    versions = versions_match[1].split()
    if len(caps) != len(versions) or len(caps) != len(set(caps)):
        raise SystemExit("install.sh: capability/version arrays are inconsistent")
    if description is None:
        if cap not in caps:
            raise SystemExit(f"install.sh: missing published capability {cap}")
        versions[caps.index(cap)] = version
    else:
        if cap in caps:
            raise SystemExit(f"install.sh: unpublished capability {cap} is already listed")
        descriptions = re.search(r"^CAP_DESC=\((.*?)\)$", text, re.MULTILINE | re.DOTALL)
        kinds = re.search(r'^CAP_SKILL_ONLY="([^"\n]*)"$', text, re.MULTILINE)
        if not descriptions or len(shlex.split(descriptions[1])) != len(caps) or not kinds:
            raise SystemExit("install.sh: capability descriptions or Skill-only list are inconsistent")
        if cap in kinds[1].split():
            raise SystemExit(f"install.sh: unpublished capability {cap} is already listed as Skill-only")
        # Quote manifest descriptions as literal Bash data, never as executable substitutions.
        text = (
            text[: descriptions.end() - 1] + "\n          " + shlex.quote(description) + text[descriptions.end() - 1 :]
        )
        if skill_only:
            text = re.sub(
                r'^CAP_SKILL_ONLY="[^"\n]*"$',
                lambda _: f'CAP_SKILL_ONLY=" {kinds[1].strip()} {cap} "',
                text,
                flags=re.MULTILINE,
            )
        caps.append(cap)
        versions.append(version)
        text = re.sub(r"^CAP_ITEMS=\([^\n]+\)$", lambda _: f"CAP_ITEMS=({' '.join(caps)})", text, flags=re.MULTILINE)
    text = re.sub(
        r"^CAP_VERSIONS=\([^\n]+\)$", lambda _: f"CAP_VERSIONS=({' '.join(versions)})", text, flags=re.MULTILINE
    )
    INSTALLER.write_text(text, encoding="utf-8")


def update_distribution_version(index: dict, marketplace: dict, version: str) -> None:
    index["distribution_version"] = version
    replace_once(FRAMEWORK, r'^__version__ = "[^"]+"', f'__version__ = "{version}"')
    metadata = marketplace.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit("marketplace: metadata must be an object")
    metadata["version"] = version


def update_manifests(cap: str, version: str, tag: str, repo_url: str = REPO_URL) -> None:
    cap_dir = CAPS / cap
    for rel in (
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        ".qoder-plugin/plugin.json",
    ):
        path = cap_dir / rel
        data = load(path)
        data["version"] = version
        if rel == ".claude-plugin/plugin.json" and "mcpServers" in data:
            server = next(iter(data["mcpServers"].values()))
            from_index = server["args"].index("--from") + 1
            server["args"][from_index] = f"qwen-mm-plugins[{cap}] @ git+{repo_url}@{tag}"
        dump(path, data)

    mcp_path = cap_dir / ".mcp.json"
    if mcp_path.exists():
        data = load(mcp_path)
        server = next(iter(data["mcpServers"].values()))
        from_index = server["args"].index("--from") + 1
        server["args"][from_index] = f"qwen-mm-plugins[{cap}] @ git+{repo_url}@{tag}"
        dump(mcp_path, data)

    packages = [p for p in cap_dir.iterdir() if p.is_dir() and p.name.isidentifier() and (p / "__init__.py").is_file()]
    if len(packages) > 1:
        raise SystemExit(f"{cap}: found multiple server packages")
    if packages:
        replace_once(packages[0] / "__init__.py", r'^__version__ = "[^"]+"$', f'__version__ = "{version}"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capability")
    parser.add_argument("version")
    parser.add_argument("--initial", action="store_true", help="register an unpublished plugin for its first release")
    parser.add_argument("--repo-url", default=REPO_URL, help="repository used by published plugin and MCP refs")
    parser.add_argument(
        "--allow-existing-tag", action="store_true", help="render metadata for verification; never changes tags"
    )
    parser.add_argument(
        "--distribution-version",
        required=True,
        help="new one-distribution/release-train semver; reuse it for every cap in one release commit",
    )
    args = parser.parse_args()
    cap, version = args.capability, args.version
    if not re.fullmatch(r"[a-z][a-z0-9-]*", cap) or cap == "example":
        parser.error("choose a capability name other than the unpublished example template")
    if not SEMVER.fullmatch(version):
        parser.error(f"version must be semver, got {version!r}")
    if not SEMVER.fullmatch(args.distribution_version):
        parser.error(f"distribution version must be semver, got {args.distribution_version!r}")

    index = load(INDEX)
    versions = index["plugins"]
    if args.initial and cap in versions:
        parser.error(f"{cap} is already published; omit --initial")
    if not args.initial and cap not in versions:
        parser.error(f"{cap} is unpublished; use --initial with an explicit first version")
    if not (CAPS / cap / ".claude-plugin/plugin.json").is_file():
        parser.error(f"missing plugin manifest for {cap}")
    tag = index["tag_format"].format(cap=cap, version=version)
    existing = subprocess.run(
        ["git", "tag", "--list", tag], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    if existing and not args.allow_existing_tag:
        parser.error(f"tag already exists locally: {tag}")

    market = load(MARKETPLACE)
    entry = next((p for p in market["plugins"] if p["name"] == f"qwen-mm-plugins-{cap}"), None)
    description = None
    if args.initial:
        if entry is not None:
            parser.error(f"marketplace: unpublished capability {cap} is already listed")
        # Validate the committed plugin structure before generating any registration metadata.
        subprocess.run([sys.executable, str(ROOT / "scripts/check_manifests.py")], cwd=ROOT, check=True)
        manifest = load(CAPS / cap / ".claude-plugin/plugin.json")
        description = manifest.get("description")
        if not isinstance(description, str) or not description.strip() or any(ord(c) < 32 for c in description):
            parser.error("the Claude plugin manifest needs a nonempty, single-line description")
        entry = {"name": manifest["name"], "description": description}
        market["plugins"].append(entry)
    elif entry is None:
        raise SystemExit(f"marketplace: missing qwen-mm-plugins-{cap}")
    versions[cap] = version
    update_distribution_version(index, market, args.distribution_version)
    entry["source"] = {
        "source": "git-subdir",
        "url": args.repo_url,
        "path": f"src/capabilities/{cap}",
        "ref": tag,
    }
    dump(INDEX, index)
    update_manifests(cap, version, tag, args.repo_url)
    update_installer(cap, version, description=description, skill_only=not (CAPS / cap / ".mcp.json").exists())
    dump(MARKETPLACE, market)

    print(f"Prepared qwen-mm-plugins-{cap} {version}")
    print(f"Distribution release train: {args.distribution_version}")
    print("Next: review the generated version PR and comment /publish to tag before merging its catalog entries.")
    print("This script did not commit, tag, or push anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
