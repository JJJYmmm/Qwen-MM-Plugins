#!/usr/bin/env python3
"""Fork-only prototype: plan changes, freeze a release, publish tags, then promote metadata.

Requires Python 3.11+. No command modifies the source checkout. Snapshot and promotion use new
clones; publishing pushes only explicitly named tags. The caller reviews/pushes the catalog branch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import tomllib

if __package__:
    from .tag_plugin_release import semver_key
else:
    from tag_plugin_release import semver_key

PROVENANCE = ".release/snapshot.json"
LEDGER = ".release/published.json"
VERSION_LINE = re.compile(r'^__version__\s*=\s*[\'"][^\'"]+[\'"]', re.MULTILINE)


def run(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True, env=env)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run(repo, "git", *args)


def read_at(repo: Path, ref: str, path: str) -> str:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(path: str, value: str) -> str:
    if path.endswith(".py"):
        return VERSION_LINE.sub('__version__ = "<release>"', value)
    if path.endswith("plugin.json") or path.endswith(".mcp.json"):
        if not value:
            return value
        data = json.loads(value)
        data.pop("version", None)
        servers = data.get("mcpServers", {})
        for server in servers.values() if isinstance(servers, dict) else []:
            args = server.get("args", [])
            if "--from" in args:
                pos = args.index("--from") + 1
                if pos < len(args) and " @ " in args[pos]:
                    args[pos] = args[pos].split(" @ ", 1)[0] + " @ <release-source>"
        return json.dumps(data, sort_keys=True)
    return value


def extra_closure(name: str, extras: dict, seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    for requirement in extras.get(name, []):
        match = re.match(r"qwen-mm-plugins\[([^]]+)\]", requirement)
        if match:
            for child in match.group(1).split(","):
                extra_closure(child.strip(), extras, seen)
    return seen


def plan(repo: Path, base: str, source: str) -> dict:
    source = git(repo, "rev-parse", f"{source}^{{commit}}")
    index = json.loads(read_at(repo, source, "plugin-versions.json"))
    ledger = json.loads(read_at(repo, source, LEDGER) or read_at(repo, base, LEDGER) or "{}")
    reasons: dict[str, list[str]] = {}
    for cap in sorted(index["plugins"]):
        baseline = ledger.get("plugins", {}).get(cap, {}).get("source_commit", base)
        changes = git(repo, "diff", "--name-only", baseline, source).splitlines()
        cap_root = f"src/capabilities/{cap}/"
        is_server = bool(read_at(repo, source, f"{cap_root}.mcp.json"))
        for path in changes:
            if path.startswith(cap_root):
                if normalized(path, read_at(repo, baseline, path)) != normalized(path, read_at(repo, source, path)):
                    reasons.setdefault(cap, []).append(path)
            elif is_server and (path.startswith("src/shared/") or path == "src/mcp_framework.py"):
                if normalized(path, read_at(repo, baseline, path)) != normalized(path, read_at(repo, source, path)):
                    reasons.setdefault(cap, []).append(path)
        if not is_server or "pyproject.toml" not in changes:
            continue
        old = tomllib.loads(read_at(repo, baseline, "pyproject.toml"))
        new = tomllib.loads(read_at(repo, source, "pyproject.toml"))
        old_extras = old.get("project", {}).pop("optional-dependencies", {})
        new_extras = new.get("project", {}).pop("optional-dependencies", {})
        if old != new:
            reasons.setdefault(cap, []).append("pyproject.toml: base/build/package settings")
        else:
            changed_extras = {
                name for name in old_extras.keys() | new_extras.keys() if old_extras.get(name) != new_extras.get(name)
            }
            used = extra_closure(cap, old_extras) | extra_closure(cap, new_extras)
            if used & changed_extras:
                reasons.setdefault(cap, []).append("pyproject.toml: " + ", ".join(sorted(used & changed_extras)))
    return {
        "source_commit": source,
        "base": base,
        "affected": reasons,
        "semver_policy": "explicit release input; diff determines scope only",
    }


def clone_at(repo: Path, ref: str, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"destination already exists: {destination}")
    git(repo, "clone", "--quiet", "--no-hardlinks", str(repo), str(destination))
    git(destination, "checkout", "--quiet", "--detach", ref)


def commit(repo: Path, source: str, message: str) -> str:
    # Identical source and release inputs produce the same commit on a retry.
    date = git(repo, "show", "-s", "--format=%cI", source)
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    git(repo, "add", "--all")
    if not git(repo, "diff", "--cached", "--name-only"):
        return git(repo, "rev-parse", "HEAD")
    run(
        repo,
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=Release snapshot prototype",
        "-c",
        "user.email=release-poc@users.noreply.github.com",
        "commit",
        "--quiet",
        "-m",
        message,
        env=env,
    )
    return git(repo, "rev-parse", "HEAD")


def prepare(repo: Path, releases: dict, distribution: str, url: str, *, existing: bool = False) -> None:
    for cap, version in sorted(releases.items()):
        options = ["--allow-existing-tag"] if existing else []
        run(
            repo,
            sys.executable,
            "scripts/prepare_plugin_release.py",
            cap,
            version,
            "--distribution-version",
            distribution,
            "--repo-url",
            url,
            *options,
        )
    run(repo, sys.executable, "scripts/check_manifests.py")
    run(repo, "bash", "-n", "install.sh")


def snapshot(repo: Path, source: str, releases: dict, distribution: str, url: str, destination: Path) -> dict:
    source = git(repo, "rev-parse", f"{source}^{{commit}}")
    clone_at(repo, source, destination)
    original = read_json(destination / "plugin-versions.json")
    for cap, version in releases.items():
        if semver_key(version) <= semver_key(original["plugins"][cap]):
            raise RuntimeError(f"release must advance {cap}'s version")
    if semver_key(distribution) <= semver_key(original["distribution_version"]):
        raise RuntimeError("snapshot must advance the distribution version")
    prepare(destination, releases, distribution, url)
    provenance = {
        "schema": 1,
        "source_commit": source,
        "repository_url": url,
        "distribution_version": distribution,
        "dependency_sha256": hashlib.sha256((destination / "pyproject.toml").read_bytes()).hexdigest(),
        "previous_versions": {cap: original["plugins"][cap] for cap in sorted(releases)},
        "plugins": {
            cap: {"version": version, "tag": original["tag_format"].format(cap=cap, version=version)}
            for cap, version in sorted(releases.items())
        },
    }
    dump(destination / PROVENANCE, provenance)
    sha = commit(
        destination,
        source,
        "release: immutable snapshot " + ", ".join(f"{cap} {version}" for cap, version in sorted(releases.items())),
    )
    return dict(provenance, release_commit=sha)


def remote_target(repo: Path, remote: str, tag: str) -> str | None:
    refs = git(repo, "ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    found = dict(line.split("\t", 1)[::-1] for line in refs.splitlines())
    return found.get(f"refs/tags/{tag}^{{}}") or found.get(f"refs/tags/{tag}")


def release_info(repo: Path) -> dict:
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("release checkout must be clean")
    info = read_json(repo / PROVENANCE)
    info["release_commit"] = git(repo, "rev-parse", "HEAD")
    index = read_json(repo / "plugin-versions.json")
    for cap, release in info["plugins"].items():
        if (
            index["plugins"][cap] != release["version"]
            or index["tag_format"].format(cap=cap, version=release["version"]) != release["tag"]
        ):
            raise RuntimeError(f"provenance does not match release metadata: {cap}")
    if hashlib.sha256((repo / "pyproject.toml").read_bytes()).hexdigest() != info["dependency_sha256"]:
        raise RuntimeError("dependency fingerprint does not match release provenance")
    return info


def verify_published(repo: Path, remote: str, info: dict) -> None:
    for release in info["plugins"].values():
        if remote_target(repo, remote, release["tag"]) != info["release_commit"]:
            raise RuntimeError(f"unpublished or conflicting tag: {release['tag']}; catalog promotion refused")


def publish(repo: Path, remote: str) -> dict:
    info = release_info(repo)
    run(repo, sys.executable, "scripts/check_manifests.py")
    pending: list[str] = []
    for cap, release in info["plugins"].items():
        tag = release["tag"]
        existing = remote_target(repo, remote, tag)
        if existing is not None:
            if existing != info["release_commit"]:
                raise RuntimeError(f"published tag must never move: {tag}")
            continue
        local = run(repo, "git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
        if local and local != info["release_commit"]:
            raise RuntimeError(f"conflicting local tag: {tag}")
        if not local:
            message = f"{cap} {release['version']}\n\nSource-Commit: {info['source_commit']}\nDistribution-Version: {info['distribution_version']}\nDependency-SHA256: {info['dependency_sha256']}\n"
            git(
                repo,
                "-c",
                "user.name=Release snapshot prototype",
                "-c",
                "user.email=release-poc@users.noreply.github.com",
                "tag",
                "-a",
                tag,
                info["release_commit"],
                "-m",
                message,
            )
        pending.append(f"refs/tags/{tag}")
    if pending:
        git(repo, "push", "--atomic", remote, *pending)
    verify_published(repo, remote, info)
    return dict(info, published=True)


def promote(repo: Path, catalog: str, released: Path, remote: str, destination: Path) -> dict:
    info = release_info(released)
    # Verify before cloning/writing the proposed catalog. Missing tags leave the old catalog intact.
    verify_published(released, remote, info)
    base = git(repo, "rev-parse", f"{catalog}^{{commit}}")
    index = json.loads(read_at(repo, base, "plugin-versions.json"))
    if semver_key(info["distribution_version"]) < semver_key(index["distribution_version"]):
        raise RuntimeError("catalog distribution version would regress; promotion refused")
    for cap, previous in info["previous_versions"].items():
        if index["plugins"][cap] not in (previous, info["plugins"][cap]["version"]):
            raise RuntimeError(f"catalog advanced independently for {cap}; regenerate the release plan")
    clone_at(repo, base, destination)
    releases = {cap: release["version"] for cap, release in info["plugins"].items()}
    # Transform metadata in the current source; never copy source/pyproject back from a snapshot.
    prepare(destination, releases, info["distribution_version"], info["repository_url"], existing=True)
    ledger = json.loads(read_at(repo, base, LEDGER) or '{"schema": 1, "plugins": {}}')
    for cap, release in info["plugins"].items():
        ledger["plugins"][cap] = dict(
            release,
            source_commit=info["source_commit"],
            release_commit=info["release_commit"],
            distribution_version=info["distribution_version"],
            dependency_sha256=info["dependency_sha256"],
        )
    dump(destination / LEDGER, ledger)
    # Version stamps change; newer server code and dependency declarations remain untouched.
    paths = git(destination, "diff", "--name-only").splitlines()
    allowed = {"plugin-versions.json", ".claude-plugin/marketplace.json", "install.sh", "src/mcp_framework.py", LEDGER}
    for cap in releases:
        cap_root = destination / "src/capabilities" / cap
        allowed.update(
            f"src/capabilities/{cap}/{rel}"
            for rel in (
                ".claude-plugin/plugin.json",
                ".codex-plugin/plugin.json",
                ".qoder-plugin/plugin.json",
                ".mcp.json",
            )
        )
        allowed.update(str(path.relative_to(destination)) for path in cap_root.glob("*/__init__.py"))
    if set(paths) - allowed:
        raise RuntimeError(f"promotion touched unexpected paths: {sorted(set(paths) - allowed)}")
    sha = commit(destination, base, "release: promote published catalog " + ", ".join(sorted(releases)))
    return {"catalog_commit": sha, "catalog_base": base, "plugins": ledger["plugins"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--base", required=True)
    planning.add_argument("--source", default="HEAD")
    freezing = sub.add_parser("snapshot")
    freezing.add_argument("--source", default="HEAD")
    freezing.add_argument("--release", action="append", required=True, metavar="CAP=VERSION")
    freezing.add_argument("--distribution-version", required=True)
    freezing.add_argument("--repo-url", required=True)
    freezing.add_argument("--destination", type=Path, required=True)
    publishing = sub.add_parser("publish")
    publishing.add_argument("--remote", required=True)
    promoting = sub.add_parser("promote")
    promoting.add_argument("--catalog", default="HEAD")
    promoting.add_argument("--snapshot", type=Path, required=True)
    promoting.add_argument("--remote", required=True)
    promoting.add_argument("--destination", type=Path, required=True)
    for command in (planning, freezing, publishing, promoting):
        command.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        if args.command == "plan":
            result = plan(repo, args.base, args.source)
        elif args.command == "snapshot":
            releases = dict(value.split("=", 1) for value in args.release)
            result = snapshot(
                repo, args.source, releases, args.distribution_version, args.repo_url, args.destination.resolve()
            )
        elif args.command == "publish":
            result = publish(repo, args.remote)
        else:
            result = promote(repo, args.catalog, args.snapshot.resolve(), args.remote, args.destination.resolve())
    except (RuntimeError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
