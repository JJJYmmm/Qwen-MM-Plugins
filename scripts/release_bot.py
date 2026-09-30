#!/usr/bin/env python3
"""Prepare a separate release PR from a maintainer's /release comment; /publish tags then merges it.

Comment text is parsed as data. Only merged source PRs and generated metadata are released.
GitHub comments/PRs/tags hold the state; no additional release ledger is stored in the source tree.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

if __package__:
    from .tag_plugin_release import semver_key
else:
    from tag_plugin_release import semver_key

ROOT = Path(__file__).resolve().parent.parent
RELEASE_BRANCH_PREFIX = "release/pr-"
VERSION = re.compile(r'^__version__\s*=\s*[\'"][^\'"]+[\'"]', re.MULTILINE)


def run(repo: Path, *args: str, input_text: str | None = None, env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=repo, input=input_text, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{args[0]} failed")
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run(repo, "git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args)


def at(repo: Path, ref: str, path: str) -> str:
    return git(repo, "show", f"{ref}:{path}")


class GitHub:
    def __init__(self, repository: str):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("invalid repository name")
        self.repository = repository

    def call(self, path: str, method: str = "GET", data: dict | None = None):
        endpoint = f"repos/{self.repository}" + (f"/{path}" if path else "")
        args = ["gh", "api", endpoint, "--method", method]
        if data is not None:
            args += ["--input", "-"]
        output = run(ROOT, *args, input_text=json.dumps(data) if data is not None else None)
        return json.loads(output) if output else None

    def pages(self, path: str) -> list:
        result = []
        for page in range(1, 101):
            items = self.call(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            result.extend(items)
            if len(items) < 100:
                return result
        raise RuntimeError("pagination limit exceeded")

    def allowed(self, login: str) -> bool:
        permission = self.call(f"collaborators/{quote(login, safe='')}/permission").get("permission")
        return permission in {"admin", "maintain", "write"}

    def reply(self, number: int, body: str) -> None:
        if not any(c["body"] == body for c in self.pages(f"issues/{number}/comments")):
            self.call(f"issues/{number}/comments", "POST", {"body": body})


def parse(body: str) -> tuple[str, dict[str, str]] | None:
    body = re.sub(r"^@github-actions(?:\[bot\])?\s+", "", body.strip())
    if not re.match(r"^/(release|publish)(?:\s|$)", body):
        return None
    words = body.split()
    if words[0] == "/publish":
        if len(words) != 1:
            raise ValueError("Use /publish without arguments on the generated release PR.")
        return "publish", {}
    if len(words) == 1:
        raise ValueError("Example: /release search=1.1.2 framework=1.1.10")
    requested: dict[str, str] = {}
    for word in words[1:]:
        if not re.fullmatch(r"[a-z][a-z0-9-]*=[A-Za-z0-9.+-]+", word):
            raise ValueError(f"Invalid release argument: {word!r}")
        name, value = word.split("=", 1)
        name = "distribution" if name in {"framework", "mcp-framework"} else name
        if name in requested:
            raise ValueError(f"Duplicate release argument: {name}")
        if value not in {"patch", "minor", "major"}:
            semver_key(value)
        requested[name] = value
    return "release", requested


def next_version(current: str, requested: str) -> str:
    if requested in {"patch", "minor", "major"}:
        major, minor, patch = semver_key(current)[:3]
        value = {
            "patch": f"{major}.{minor}.{patch + 1}",
            "minor": f"{major}.{minor + 1}.0",
            "major": f"{major + 1}.0.0",
        }
        requested = value[requested]
    if semver_key(requested) <= semver_key(current):
        raise ValueError(f"Version must advance: {current} -> {requested}")
    return requested


def resolve(index: dict, requested: dict) -> tuple[dict, str]:
    unknown = requested.keys() - index["plugins"].keys() - {"distribution", "all-plugins"}
    if unknown:
        raise ValueError(f"Unknown plugins: {', '.join(sorted(unknown))}")
    selected = {cap: value for cap, value in requested.items() if cap not in {"distribution", "all-plugins"}}
    if "all-plugins" in requested:
        selected = {**dict.fromkeys(index["plugins"], requested["all-plugins"]), **selected}
    if not selected:
        raise ValueError(
            "Select plugins explicitly, e.g. search=patch, or use all-plugins=patch to release every listed plugin."
        )
    releases = {cap: next_version(index["plugins"][cap], value) for cap, value in sorted(selected.items())}
    distribution = next_version(index["distribution_version"], requested.get("distribution", "patch"))
    # Stable versions and numeric rc versions map unambiguously to the Python wheel version.
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", distribution):
        raise ValueError("Distribution version must be X.Y.Z or X.Y.Z-rc.NUMBER (Python-compatible).")
    return releases, distribution


def clone_at(repo: Path, source: str, destination: Path) -> None:
    git(repo, "clone", "--quiet", "--no-local", str(repo), str(destination))
    git(destination, "fetch", "--quiet", "--no-tags", str(repo), source)
    git(destination, "checkout", "--quiet", "--detach", source)


def prepare(repo: Path, releases: dict, distribution: str, url: str, *, existing: bool = False) -> None:
    for cap, version in releases.items():
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
            *(["--allow-existing-tag"] if existing else []),
        )
    run(repo, sys.executable, "scripts/check_manifests.py")
    run(repo, "bash", "-n", "install.sh")


def commit(repo: Path, source: str, message: str) -> str:
    date = git(repo, "show", "-s", "--format=%cI", source)
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    git(repo, "add", "--all")
    run(
        repo,
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=Release bot",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit",
        "--quiet",
        "-m",
        message,
        env=env,
    )
    return git(repo, "rev-parse", "HEAD")


def shared_changed(repo: Path, source: str, index: dict, servers: set[str]) -> bool:
    entries = {
        p["name"].removeprefix("qwen-mm-plugins-"): p
        for p in json.loads(at(repo, source, ".claude-plugin/marketplace.json"))["plugins"]
    }
    for cap in sorted(servers):
        tag = index["tag_format"].format(cap=cap, version=index["plugins"][cap])
        # Read the catalog's actual repository URL, including upstream stable refs in a fork.
        url = entries[cap]["source"]["url"]
        git(repo, "fetch", "--quiet", "--no-tags", url, f"refs/tags/{tag}")
        baseline = git(repo, "rev-parse", "FETCH_HEAD^{commit}")
        paths = git(
            repo, "diff", "--name-only", baseline, source, "--", "src/shared", "src/mcp_framework.py", "pyproject.toml"
        ).splitlines()
        for path in paths:
            if path != "src/mcp_framework.py":
                return True
            if VERSION.sub("<version>", at(repo, baseline, path)) != VERSION.sub("<version>", at(repo, source, path)):
                return True
    return False


def mcp_plugins(repo: Path, source: str, index: dict) -> set[str]:
    paths = git(repo, "ls-tree", "-r", "--name-only", source, "--", "src/capabilities").splitlines()
    return {path.split("/")[2] for path in paths if path.endswith("/.mcp.json")} & index["plugins"].keys()


def shared_notice(repo: Path, source: str, releases: dict) -> str:
    index = json.loads(at(repo, source, "plugin-versions.json"))
    servers = mcp_plugins(repo, source, index)
    selected = servers & releases.keys()
    if not selected or not shared_changed(repo, source, index, selected):
        return ""
    notice = (
        "Shared runtime or dependency changes are included relative to at least one selected plugin's published tag. "
        "The release scope follows your explicit selection. Review compatibility for the selected plugins."
    )
    remaining = sorted(servers - releases.keys())
    if remaining:
        notice += (
            " Other MCP plugins keep their published refs and framework snapshots: "
            + ", ".join(f"`{cap}`" for cap in remaining)
            + ". To roll this change out more widely, close this unpublished version PR and submit a new request "
            "listing the additional plugins, or use `all-plugins=patch` for every listed plugin, including Skill-only plugins."
        )
    return notice + "\n\n"


def candidate_info(repo: Path, head: str, base: str, url: str) -> dict:
    parents = git(repo, "show", "-s", "--format=%P", head).split()
    if len(parents) != 1:
        raise ValueError("Release candidate must be one generated commit on its source; regenerate before publication.")
    source = parents[0]
    git(repo, "merge-base", "--is-ancestor", source, base)
    before = json.loads(at(repo, source, "plugin-versions.json"))
    after = json.loads(at(repo, head, "plugin-versions.json"))
    if before["plugins"].keys() != after["plugins"].keys():
        raise ValueError("This release workflow handles existing plugins; plugin onboarding requires its own review.")
    releases = {cap: value for cap, value in after["plugins"].items() if value != before["plugins"][cap]}
    if not releases:
        raise ValueError("Release PR has no plugin version changes.")
    releases, distribution = resolve(before, {**releases, "distribution": after["distribution_version"]})
    # Re-render only metadata from an already-merged source. Reject added code, workflows, or
    # launcher changes before running any release-candidate tests with a privileged trigger.
    with tempfile.TemporaryDirectory(prefix="qmp-verify-release-") as temporary:
        checkout = Path(temporary) / "repo"
        clone_at(repo, source, checkout)
        prepare(checkout, releases, distribution, url, existing=True)
        git(checkout, "add", "--all")
        if git(checkout, "write-tree") != git(repo, "rev-parse", f"{head}^{{tree}}"):
            raise ValueError("Release PR contains changes beyond generated versions and refs.")
    return {
        "source": source,
        "head": head,
        "plugins": releases,
        "distribution": distribution,
        "tag_format": after["tag_format"],
    }


def branch_for(number: int, comment_id: int) -> str:
    return f"{RELEASE_BRANCH_PREFIX}{number}-request-{comment_id}"


def base_state(api: GitHub, repo: Path) -> tuple[str, str, str]:
    metadata = api.call("")
    base = metadata["default_branch"]
    url = metadata["clone_url"]
    git(repo, "fetch", "--quiet", "--no-tags", url, f"refs/heads/{base}")
    return base, git(repo, "rev-parse", "FETCH_HEAD^{commit}"), url


def make_release(api: GitHub, repo: Path, number: int, comment: dict, requested: dict) -> str:
    pr = api.call(f"pulls/{number}")
    base, source, url = base_state(api, repo)
    if pr["base"]["ref"] != base or pr["base"]["repo"]["full_name"] != api.repository:
        raise ValueError(f"Source PR must target {api.repository}:{base}.")
    if pr["head"]["ref"].startswith(RELEASE_BRANCH_PREFIX):
        raise ValueError("Use /publish on a release PR. Put /release on the source-code PR.")
    if not pr["merged"]:
        if pr["state"] != "open":
            raise ValueError("Source PR was closed without merging.")
        return f"Release request recorded. After this code PR merges into `{base}`, I will prepare a separate version PR. No tag has been published."
    git(repo, "merge-base", "--is-ancestor", pr["merge_commit_sha"], source)
    branch = branch_for(number, comment["id"])
    existing = api.pages(f"pulls?state=all&head={quote(api.repository.split('/')[0] + ':' + branch, safe='')}")
    if existing:
        return f"This request already has a version PR: {existing[0]['html_url']} (state: {existing[0]['state']})."
    pending = [
        p
        for p in api.pages(f"pulls?state=open&base={quote(base, safe='')}")
        if p["head"]["ref"].startswith(RELEASE_BRANCH_PREFIX)
    ]
    if pending:
        raise ValueError(
            f"Finish or close the pending version PR first: {pending[0]['html_url']}. Then submit the release request again."
        )
    with tempfile.TemporaryDirectory(prefix="qmp-release-pr-") as temporary:
        checkout = Path(temporary) / "repo"
        remote_branch = git(repo, "ls-remote", "--heads", url, f"refs/heads/{branch}")
        if remote_branch:
            head = remote_branch.split()[0]
            git(repo, "fetch", "--quiet", "--no-tags", url, head)
            info = candidate_info(repo, head, source, url)
        else:
            index = json.loads(at(repo, source, "plugin-versions.json"))
            clone_at(repo, source, checkout)
            releases, distribution = resolve(index, requested)
            prepare(checkout, releases, distribution, url)
            head = commit(
                checkout,
                source,
                f"release: prepare versions from #{number}\n\nSource-Commit: {source}\nSource-Comment: {comment['id']}",
            )
            info = {"source": source, "plugins": releases, "distribution": distribution}
        notice = shared_notice(repo, info["source"], info["plugins"])
        if not remote_branch:
            git(checkout, "push", url, f"{head}:refs/heads/{branch}")
        versions = "\n".join(f"- `{cap}` → `{version}`" for cap, version in sorted(info["plugins"].items()))
        body = (
            f"Prepare released versions for source PR #{number}. Source commit: `{info['source']}`.\n\n"
            f"{versions}\n\nPython distribution / framework: `{info['distribution']}`.\n\n"
            f"{notice}"
            "This PR changes generated version/ref metadata only. Review this diff, then comment `/publish` to run release checks, publish immutable tags, and merge this PR with a merge commit. "
            "Do not merge this PR before its tags exist. Only explicitly selected plugins are released.\n"
        )
        created = api.call(
            "pulls", "POST", {"title": f"release: versions from #{number}", "head": branch, "base": base, "body": body}
        )
        return f"Version PR ready: {created['html_url']}\n\n{versions}\n\n{notice}Distribution/framework: `{info['distribution']}`. Review it and comment `/publish` there to release."


def release_candidate(api: GitHub, repo: Path, number: int, expected: str | None = None) -> tuple[dict, str]:
    pr = api.call(f"pulls/{number}")
    base, current, url = base_state(api, repo)
    if (
        pr["base"]["ref"] != base
        or pr["base"]["repo"]["full_name"] != api.repository
        or not pr["head"].get("repo")
        or pr["head"]["repo"]["full_name"] != api.repository
        or not pr["head"]["ref"].startswith(RELEASE_BRANCH_PREFIX)
    ):
        raise ValueError("/publish only accepts a generated version PR in this repository.")
    if pr["state"] != "open" and not pr["merged"]:
        raise ValueError("Version PR was closed without merging.")
    head = pr["head"]["sha"]
    if expected and head != expected:
        raise ValueError("Version PR changed after verification; submit /publish again.")
    git(repo, "fetch", "--quiet", "--no-tags", url, head)
    info = candidate_info(repo, head, current, url)
    info["merged"] = pr["merged"]
    return info, url


def comment_command(api: GitHub, number: int, comment_id: int) -> tuple[dict, tuple | None]:
    comment = api.call(f"issues/comments/{comment_id}")
    if comment["issue_url"].rstrip("/").split("/")[-1] != str(number):
        raise ValueError("Comment does not belong to this PR.")
    if comment["user"]["type"] != "User" or not api.allowed(comment["user"]["login"]):
        return comment, None
    return comment, parse(comment["body"])


def handle_event(api: GitHub, repo: Path, event: dict) -> dict:
    if "comment" in event:
        if event.get("action") != "created" or "pull_request" not in event.get("issue", {}):
            return {}
        number, comment_id = event["issue"]["number"], event["comment"]["id"]
    elif event.get("action") == "closed" and event.get("pull_request", {}).get("merged"):
        number = event["number"]
        comment_id = None
        # The latest authorized release request wins. Publishing remains an explicit action
        # on the separate version PR, never a side effect of merging arbitrary source code.
        for item in reversed(api.pages(f"issues/{number}/comments")):
            if not re.match(r"^(?:@github-actions(?:\[bot\])?\s+)?/release(?:\s|$)", item["body"].strip()):
                continue
            if item["user"]["type"] == "User" and api.allowed(item["user"]["login"]):
                comment_id = item["id"]
                break
        if comment_id is None:
            return {}
    else:
        return {}
    try:
        comment, command = comment_command(api, number, comment_id)
        if command is None:
            return {}
        action, requested = command
        if action == "release":
            api.reply(number, make_release(api, repo, number, comment, requested))
            return {}
        info, _ = release_candidate(api, repo, number)
        return {"head": info["head"], "number": number, "comment": comment_id}
    except (ValueError, RuntimeError) as exc:
        api.reply(number, f"Release request could not proceed: {exc}")
        raise


def remote_tag_target(repo: Path, url: str, tag: str) -> str | None:
    ref = f"refs/tags/{tag}"
    refs = dict(line.split()[::-1] for line in git(repo, "ls-remote", "--tags", url, ref, f"{ref}^{{}}").splitlines())
    # Annotated tags resolve through the peeled ref; lightweight tags point directly at a commit.
    return refs.get(f"{ref}^{{}}", refs.get(ref))


def publish_tags(repo: Path, url: str, info: dict) -> None:
    tags = [info["tag_format"].format(cap=cap, version=version) for cap, version in info["plugins"].items()]
    pending = []
    for tag in tags:
        git(repo, "check-ref-format", f"refs/tags/{tag}")
        target = remote_tag_target(repo, url, tag)
        if target:
            if target != info["head"]:
                raise ValueError(f"Published tag {tag} points elsewhere; choose a new version. Tags are never moved.")
            continue
        # An isolated clone avoids overwriting even a conflicting local tag on retry.
        message = f"Release {tag}\n\nSource-Commit: {info['source']}\nDistribution: {info['distribution']}"
        git(
            repo,
            "-c",
            "user.name=Release bot",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "-c",
            "tag.gpgsign=false",
            "tag",
            "-a",
            tag,
            info["head"],
            "-m",
            message,
        )
        pending.append(f"refs/tags/{tag}")
    if pending:
        git(repo, "push", "--atomic", url, *pending)
    for tag in tags:
        if remote_tag_target(repo, url, tag) != info["head"]:
            raise RuntimeError(f"Published tag could not be verified: {tag}")


def publish(api: GitHub, repo: Path, number: int, comment_id: int, expected: str) -> None:
    _, command = comment_command(api, number, comment_id)
    if command != ("publish", {}):
        raise ValueError("The authorized /publish comment is no longer present.")
    info, url = release_candidate(api, repo, number, expected)
    with tempfile.TemporaryDirectory(prefix="qmp-publish-") as temporary:
        checkout = Path(temporary) / "repo"
        clone_at(repo, expected, checkout)
        publish_tags(checkout, url, info)
    if not info["merged"]:
        # GitHub checks the expected head, required checks/reviews and merge conflicts.
        # Merge commits preserve the exact tagged commit in main's history.
        result = api.call(f"pulls/{number}/merge", "PUT", {"sha": expected, "merge_method": "merge"})
        if not result.get("merged"):
            raise RuntimeError(
                f"Tags exist; PR merge needs attention. Retry /publish after resolving it: {result.get('message')}"
            )
    api.reply(
        number,
        f"Published immutable tags at `{expected}` and merged this version PR. Plugin code and MCP refs now resolve to the same release snapshot.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["event", "publish"])
    parser.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY"), required=not os.environ.get("GITHUB_REPOSITORY")
    )
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--number", type=int)
    parser.add_argument("--comment", type=int)
    parser.add_argument("--head")
    args = parser.parse_args()
    api = GitHub(args.repository)
    try:
        if args.action == "event":
            if not args.event:
                parser.error("event requires --event or GITHUB_EVENT_PATH")
            outputs = handle_event(api, args.repo, json.loads(args.event.read_text()))
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                    for key, value in outputs.items():
                        print(f"{key}={value}", file=stream)
            print(json.dumps(outputs))
        else:
            if not (args.number and args.comment and args.head):
                parser.error("publish requires --number, --comment and --head")
            publish(api, args.repo, args.number, args.comment, args.head)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
