"""Release authorization, immutable refs, and harness metadata regression checks (offline)."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("release_bot", ROOT / "scripts/release_bot.py")
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


@pytest.mark.parametrize("body", ["/release search=1.2.3", "@github-actions /release search=1.2.3"])
def test_release_command(body):
    assert bot.parse(body) == ("release", {"search": "1.2.3"})
    assert bot.parse("/release framework=1.2.3 mhs=patch")[1] == {"distribution": "1.2.3", "mhs": "patch"}


@pytest.mark.parametrize(
    "body",
    [
        "/release",
        "/publish search=patch",
        "/release search=$(id)",
        "/release search=1.2.3;id",
        "/release framework=patch distribution=minor",
    ],
)
def test_invalid_commands(body):
    with pytest.raises(ValueError):
        bot.parse(body)
    assert bot.parse("please /release search=1.2.3") is None


def test_shared_runtime_releases_all_servers_but_not_skill_only():
    index = {"distribution_version": "1.0.0", "plugins": dict.fromkeys(["search", "mhs", "edu-agent"], "1.0.0")}
    assert bot.resolve(index, {"search": "minor"}, {"search", "mhs"}, False) == ({"search": "1.1.0"}, "1.0.1")
    assert bot.resolve(index, {"search": "minor"}, {"search", "mhs"}, True) == (
        {"mhs": "1.0.1", "search": "1.1.0"},
        "1.0.1",
    )
    assert bot.resolve(index, {"distribution": "1.2.0"}, {"search", "mhs"}, False)[0] == {
        "mhs": "1.0.1",
        "search": "1.0.1",
    }
    with pytest.raises(ValueError, match="Unknown"):
        bot.resolve(index, {"typo": "patch"}, {"search"}, False)
    with pytest.raises(ValueError, match="must advance"):
        bot.next_version("1.2.3", "1.2.3")


class FakeAPI:
    repository = "owner/repo"

    def __init__(self, *, permission=True, body="/publish"):
        self.permission = permission
        self.comment = {
            "id": 8,
            "body": body,
            "issue_url": "https://api.github.com/repos/owner/repo/issues/7",
            "user": {"type": "User", "login": "maintainer"},
        }
        self.replies = []

    def call(self, path):
        assert path == "issues/comments/8"
        return self.comment

    def pages(self, path):
        return [self.comment]

    def allowed(self, login):
        return self.permission

    def reply(self, number, body):
        self.replies.append(body)


EVENT = {"action": "created", "issue": {"number": 7, "pull_request": {}}, "comment": {"id": 8, "body": "/publish"}}


def test_unauthorized_comment_cannot_prepare_or_publish(tmp_path):
    assert bot.handle_event(FakeAPI(permission=False), tmp_path, EVENT) == {}


def test_live_comment_wins_over_event_payload(tmp_path):
    assert bot.handle_event(FakeAPI(body="cancelled"), tmp_path, EVENT) == {}
    api = FakeAPI()
    api.comment["issue_url"] = "https://api.github.com/repos/owner/repo/issues/99"
    with pytest.raises(ValueError, match="belong"):
        bot.handle_event(api, tmp_path, EVENT)


def test_publish_rechecks_authorization_before_accessing_candidate(tmp_path):
    with pytest.raises(ValueError, match="authorized"):
        bot.publish(FakeAPI(permission=False), tmp_path, 7, 8, "a" * 40)


def test_queued_request_runs_only_after_merge(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bot, "make_release", lambda *args: calls.append(args[2]) or "prepared")
    api = FakeAPI(body="/release search=patch")
    assert bot.handle_event(api, tmp_path, {"action": "closed", "number": 7, "pull_request": {"merged": False}}) == {}
    assert not calls
    bot.handle_event(api, tmp_path, {"action": "closed", "number": 7, "pull_request": {"merged": True}})
    assert calls == [7]


@pytest.fixture
def release_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Fresh history and no inherited tags: works on a shallow CI checkout and released refs.
    archive = tmp_path / "source.tar"
    subprocess.run(["git", "archive", "HEAD", "-o", str(archive)], cwd=ROOT, check=True)
    subprocess.run(["tar", "-xf", str(archive), "-C", str(repo)], check=True)
    shutil.copyfile(ROOT / "scripts/prepare_plugin_release.py", repo / "scripts/prepare_plugin_release.py")
    bot.git(repo, "init", "--initial-branch=main")
    bot.git(repo, "config", "user.name", "Release Test")
    bot.git(repo, "config", "user.email", "release@example.test")
    bot.git(repo, "add", ".")
    bot.git(repo, "commit", "-m", "source")
    source = bot.git(repo, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    bot.git(repo, "init", "--bare", str(remote))
    bot.git(repo, "push", str(remote), "HEAD:refs/heads/main")
    return repo, source, str(remote)


def test_generated_candidate_preserves_harness_shapes_and_rejects_code_changes(release_repo):
    repo, source, remote = release_repo
    index = json.loads((repo / "plugin-versions.json").read_text())
    releases = {cap: bot.next_version(index["plugins"][cap], "patch") for cap in ["search", "edu-agent"]}
    dist = bot.next_version(index["distribution_version"], "patch")
    bot.prepare(repo, releases, dist, remote)
    head = bot.commit(repo, source, "release")
    info = bot.candidate_info(repo, head, source, remote)
    assert info["plugins"] == releases
    for cap in releases:
        for manifest in [".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".qoder-plugin/plugin.json"]:
            path = f"src/capabilities/{cap}/{manifest}"
            before, after = (json.loads(bot.at(repo, sha, path)) for sha in [source, head])
            assert before.keys() == after.keys()
            for key in before.keys() - {"version", "mcpServers"}:
                assert before[key] == after[key]
    assert not (repo / "src/capabilities/edu-agent/.mcp.json").exists()
    assert (
        bot.at(repo, source, "install.sh").split("CAP_VERSIONS=", 1)[1].split("\n", 1)[1]
        == bot.at(repo, head, "install.sh").split("CAP_VERSIONS=", 1)[1].split("\n", 1)[1]
    )
    (repo / "src/mcp_framework.py").write_text((repo / "src/mcp_framework.py").read_text() + "\n# injected\n")
    bot.git(repo, "add", ".")
    bot.git(repo, "commit", "--amend", "--no-edit")
    with pytest.raises(ValueError, match="beyond generated"):
        bot.candidate_info(repo, bot.git(repo, "rev-parse", "HEAD"), source, remote)


def test_tags_precede_catalog_merge_and_retries_never_move_them(release_repo, tmp_path):
    repo, source, remote = release_repo
    index = json.loads((repo / "plugin-versions.json").read_text())
    releases = {"search": bot.next_version(index["plugins"]["search"], "patch")}
    distribution = bot.next_version(index["distribution_version"], "patch")
    bot.prepare(repo, releases, distribution, remote)
    head = bot.commit(repo, source, "release")
    info = bot.candidate_info(repo, head, source, remote)
    bot.publish_tags(repo, remote, info)
    before = bot.git(repo, "ls-remote", remote, "refs/tags/*")
    assert bot.git(repo, "ls-remote", remote, "refs/heads/main").split()[0] == source
    bot.publish_tags(repo, remote, info)
    assert bot.git(repo, "ls-remote", remote, "refs/tags/*") == before
    with pytest.raises(ValueError, match="never moved"):
        bot.publish_tags(repo, remote, {**info, "head": source})
    main = tmp_path / "main"
    bot.clone_at(repo, source, main)
    bot.git(main, "config", "user.name", "Release Test")
    bot.git(main, "config", "user.email", "release@example.test")
    (main / "unrelated.txt").write_text("concurrent main update")
    bot.git(main, "add", ".")
    bot.git(main, "commit", "-m", "concurrent code")
    bot.git(main, "fetch", str(repo), head)
    bot.git(main, "merge", "--no-ff", "--no-edit", head)
    bot.git(main, "merge-base", "--is-ancestor", head, "HEAD")
    assert (main / "unrelated.txt").read_text() == "concurrent main update"
    assert bot.git(main, "ls-remote", remote, "refs/tags/*") == before
