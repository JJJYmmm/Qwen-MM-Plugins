"""Comment on a completed Hub check using only GitHub API metadata, never PR artifacts."""

import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

MARKER = "<!-- qwen-mm-plugins-hub -->"
WORKFLOW = "hub-check.yml"


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, payload=None):
        request = Request(
            "https://api.github.com" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "qwen-mm-plugins-hub-comment",
            },
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def pages(self, path, key=None):
        results = []
        for page in range(1, 51):
            response = self.request("GET", f"{path}?per_page=100&page={page}")
            items = response[key] if key else response
            results.extend(items)
            if len(items) < 100:
                return results
        raise ValueError("Refusing to comment with an incomplete paginated result")


def eligible_pr(pr, repository, sha):
    return (
        pr.get("state") == "open"
        and pr.get("base", {}).get("repo", {}).get("full_name", "").lower() == repository.lower()
        and pr.get("head", {}).get("sha") == sha
        and isinstance(pr.get("number"), int)
        and pr["number"] > 0
    )


def comment_body(repository, run, artifact):
    conclusion = run["conclusion"]
    labels = {
        "success": "✅ Passed",
        "failure": "❌ Failed",
        "cancelled": "⚪ Cancelled",
        "timed_out": "❌ Timed out",
        "action_required": "⏳ Requires maintainer attention",
    }
    status = labels.get(conclusion, "⚪ Not completed successfully")
    base = f"https://github.com/{repository}/actions/runs/{run['id']}"
    lines = [
        MARKER,
        f"<!-- hub-run:{run['id']}:{run.get('run_attempt', 1)} -->",
        f"### Hub documentation — {status}",
        "",
        f"PR commit: `{run['head_sha'][:12]}` · [Build details]({base})",
        "",
    ]
    if conclusion == "success" and artifact:
        lines.append(
            f"[Download the static preview package]({base}/artifacts/{artifact['id']}) (GitHub sign-in required; retained for 7 days)."
        )
        lines.append(
            "Extract it and run `python3 -m http.server 8000` in that directory, then open `http://localhost:8000`. Only run previews from PRs you trust."
        )
    elif conclusion == "success":
        lines.append(
            "The build passed, but its preview package is unavailable or expired. Rerun the check to create a new package."
        )
    else:
        lines.append("Open the build details for diagnostics. No preview was published.")
    lines.extend(
        [
            "",
            "The public Hub is unchanged by this PR. After merge, the automatic upstream refresh updates it once the referenced release tags are available.",
        ]
    )
    return "\n".join(lines)


def update_comments(api, repository, run_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("Invalid repository or workflow run ID")
    prefix = "/repos/" + repository
    run = api.request("GET", f"{prefix}/actions/runs/{run_id}")
    workflow = api.request("GET", f"{prefix}/actions/workflows/{WORKFLOW}")
    if (
        run.get("workflow_id") != workflow["id"]
        or run.get("event") != "pull_request"
        or run.get("status") != "completed"
        or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))
    ):
        return 0
    sha = run["head_sha"]
    # The workflow_run pull_requests array may be empty for fork PRs. Resolve via
    # GitHub's commit association, and independently verify each current PR head.
    candidates = api.pages(f"{prefix}/commits/{sha}/pulls")
    artifacts = api.pages(f"{prefix}/actions/runs/{run_id}/artifacts", "artifacts")
    artifact = next(
        (
            a
            for a in artifacts
            if (
                a.get("name") == f"hub-preview-{sha}-{run.get('run_attempt', 1)}"
                and not a.get("expired", True)
                and isinstance(a.get("id"), int)
                and a["id"] > 0
            )
        ),
        None,
    )
    body = comment_body(repository, run, artifact)
    count = 0
    for candidate in candidates:
        if not eligible_pr(candidate, repository, sha):
            continue
        number = candidate["number"]
        comments = api.pages(f"{prefix}/issues/{number}/comments")
        owned = [
            c
            for c in comments
            if (
                c.get("user", {}).get("login") == "github-actions[bot]"
                and c.get("user", {}).get("type") == "Bot"
                and MARKER in (c.get("body") or "")
            )
        ]
        existing = owned[-1] if owned else None
        if existing:
            previous = re.search(r"<!-- hub-run:(\d+):(\d+) -->", existing["body"])
            if previous and tuple(map(int, previous.groups())) > (run_id, run.get("run_attempt", 1)):
                continue
            if existing["body"] == body:
                continue
        pr = api.request("GET", f"{prefix}/pulls/{number}")
        if not eligible_pr(pr, repository, sha):
            continue
        if existing:
            api.request("PATCH", f"{prefix}/issues/comments/{existing['id']}", {"body": body})
        else:
            api.request("POST", f"{prefix}/issues/{number}/comments", {"body": body})
        count += 1
    return count


def main():
    # These are GitHub Actions credentials/context, not plugin runtime settings.
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    count = update_comments(
        GitHub(os.environ["GH_TOKEN"]), os.environ["GITHUB_REPOSITORY"], event["workflow_run"]["id"]
    )
    print(f"Updated {count} Hub PR comment(s).")


if __name__ == "__main__":
    main()
