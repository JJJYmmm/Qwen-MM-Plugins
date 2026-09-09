"""The privileged comment step consumes API metadata, not code or preview artifacts."""

from copy import deepcopy

import pytest
from scripts.hub_pr_comment import MARKER, comment_body, update_comments

REPOSITORY = "QwenLM/Qwen-MM-Plugins"
SHA = "a" * 40


class FakeGitHub:
    def __init__(self):
        self.run = {
            "id": 10,
            "workflow_id": 20,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": SHA,
            "run_attempt": 1,
            "pull_requests": [],  # Fork runs may have no PRs in this field.
        }
        self.pr = {"number": 7, "state": "open", "base": {"repo": {"full_name": REPOSITORY}}, "head": {"sha": SHA}}
        self.current_pr = None
        self.comments = []
        self.artifacts = [{"id": 30, "name": f"hub-preview-{SHA}-1", "expired": False}]
        self.writes = []
        self.reads = []

    def request(self, method, path, payload=None):
        if method != "GET":
            self.writes.append((method, path, payload))
            if method == "POST":
                self.comments.append(
                    {"id": 50, "body": payload["body"], "user": {"login": "github-actions[bot]", "type": "Bot"}}
                )
            else:
                self.comments[-1]["body"] = payload["body"]
            return {}
        self.reads.append(path)
        if path.endswith("/actions/runs/10"):
            return self.run
        if path.endswith("/actions/workflows/hub-check.yml"):
            return {"id": 20}
        if path.endswith("/pulls/7"):
            return self.current_pr or self.pr
        raise AssertionError(f"Unexpected API read: {path}")

    def pages(self, path, key=None):
        self.reads.append(path)
        if path.endswith(f"/commits/{SHA}/pulls"):
            return [self.pr]
        if path.endswith("/artifacts"):
            return self.artifacts
        if path.endswith("/issues/7/comments"):
            return self.comments
        raise AssertionError(f"Unexpected paginated read: {path}")


def test_fork_run_creates_one_comment_and_repeated_runs_do_not_spam():
    api = FakeGitHub()
    assert update_comments(api, REPOSITORY, 10) == 1
    assert update_comments(api, REPOSITORY, 10) == 0
    assert len(api.writes) == 1
    body = api.writes[0][2]["body"]
    assert "actions/runs/10/artifacts/30" in body
    assert "7 days" in body and "PR commit: `aaaaaaaaaaaa`" in body
    assert all("/zip" not in path and "/download" not in path for path in api.reads)


def test_new_result_updates_only_the_bot_owned_comment():
    api = FakeGitHub()
    update_comments(api, REPOSITORY, 10)
    api.run["conclusion"] = "failure"
    assert update_comments(api, REPOSITORY, 10) == 1
    assert api.writes[-1][0] == "PATCH"
    assert "❌ Failed" in api.writes[-1][2]["body"]
    assert "/artifacts/" not in api.writes[-1][2]["body"]


@pytest.mark.parametrize("login,kind", [("someone", "User"), ("another[bot]", "Bot")])
def test_a_spoofed_marker_in_someone_elses_comment_is_not_edited(login, kind):
    api = FakeGitHub()
    api.comments = [{"id": 99, "body": MARKER, "user": {"login": login, "type": kind}}]
    update_comments(api, REPOSITORY, 10)
    assert api.writes[0][0] == "POST"
    assert api.comments[0]["body"] == MARKER


@pytest.mark.parametrize(
    "change",
    [
        {"state": "closed"},
        {"head": {"sha": "b" * 40}},
        {"base": {"repo": {"full_name": "another/repository"}}},
    ],
)
def test_closed_stale_or_unrelated_prs_are_ignored(change):
    api = FakeGitHub()
    api.pr.update(change)
    assert update_comments(api, REPOSITORY, 10) == 0
    assert not api.writes


def test_head_is_checked_again_immediately_before_writing():
    api = FakeGitHub()
    api.current_pr = deepcopy(api.pr)
    api.current_pr["head"]["sha"] = "b" * 40
    assert update_comments(api, REPOSITORY, 10) == 0
    assert not api.writes


@pytest.mark.parametrize(
    "change", [{"workflow_id": 999}, {"event": "push"}, {"status": "in_progress"}, {"head_sha": "not-a-sha"}]
)
def test_unrelated_or_incomplete_workflow_runs_are_ignored(change):
    api = FakeGitHub()
    api.run.update(change)
    assert update_comments(api, REPOSITORY, 10) == 0
    assert not api.writes


@pytest.mark.parametrize("run_id,attempt", [(11, 1), (10, 2)])
def test_older_runs_cannot_overwrite_a_newer_result(run_id, attempt):
    api = FakeGitHub()
    newer = {**api.run, "id": run_id, "run_attempt": attempt}
    api.comments = [
        {
            "id": 50,
            "body": comment_body(REPOSITORY, newer, None),
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        }
    ]
    assert update_comments(api, REPOSITORY, 10) == 0


def test_expired_or_previous_attempt_artifacts_are_not_advertised():
    api = FakeGitHub()
    api.artifacts[0]["expired"] = True
    api.artifacts.append({"id": 31, "name": f"hub-preview-{SHA}-0", "expired": False})
    update_comments(api, REPOSITORY, 10)
    assert "unavailable or expired" in api.writes[0][2]["body"]
    assert "/artifacts/" not in api.writes[0][2]["body"]
