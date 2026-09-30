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


def test_only_explicit_plugins_release_unless_all_mcp_is_requested():
    index = {"distribution_version": "1.0.0", "plugins": dict.fromkeys(["search", "mhs", "edu-agent"], "1.0.0")}
    assert bot.resolve(index, {"search": "minor"}, {"search", "mhs"}) == ({"search": "1.1.0"}, "1.0.1")
    assert bot.resolve(index, {"all-mcp": "patch", "search": "minor"}, {"search", "mhs"}) == (
        {"mhs": "1.0.1", "search": "1.1.0"},
        "1.0.1",
    )
    assert bot.resolve(index, {"search": "patch", "distribution": "1.2.0"}, {"search", "mhs"}) == (
        {"search": "1.0.1"},
        "1.2.0",
    )
    assert bot.resolve(index, {"all-mcp": "1.3.0"}, {"search", "mhs"})[0] == {"mhs": "1.3.0", "search": "1.3.0"}
    with pytest.raises(ValueError, match="Select plugins explicitly"):
        bot.resolve(index, {"distribution": "1.2.0"}, {"search", "mhs"})
    with pytest.raises(ValueError, match="Unknown"):
        bot.resolve(index, {"typo": "patch"}, {"search"})
    with pytest.raises(ValueError, match="must advance"):
        bot.next_version("1.2.3", "1.2.3")
    assert bot.resolve(index, {"edu-agent": "patch"}, {"search", "mhs"})[0] == {"edu-agent": "1.0.1"}


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


def test_repository_endpoint_has_no_trailing_slash(monkeypatch):
    calls = []
    monkeypatch.setattr(bot, "run", lambda repo, *args, **kwargs: calls.append(args) or "{}")
    bot.GitHub("owner/repo").call("")
    assert calls[0][2] == "repos/owner/repo"


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


def test_shared_detection_ignores_version_stamp_but_finds_runtime_and_dependencies(release_repo):
    repo, source, remote = release_repo
    index = json.loads((repo / "plugin-versions.json").read_text())
    catalog_path = repo / ".claude-plugin/marketplace.json"
    catalog = json.loads(catalog_path.read_text())
    next(p for p in catalog["plugins"] if p["name"] == "qwen-mm-plugins-search")["source"]["url"] = remote
    catalog_path.write_text(json.dumps(catalog))
    source = bot.commit(repo, source, "point test catalog at local remote")
    tag = index["tag_format"].format(cap="search", version=index["plugins"]["search"])
    bot.git(repo, "tag", tag, source)
    bot.git(repo, "push", remote, f"refs/tags/{tag}")
    framework = repo / "src/mcp_framework.py"
    framework.write_text(bot.VERSION.sub('__version__ = "999.0.0"', framework.read_text()))
    stamp = bot.commit(repo, source, "stamp only")
    assert not bot.shared_changed(repo, stamp, index, {"search"})
    assert bot.shared_notice(repo, stamp, {"search": "999.0.0"}) == ""
    framework.write_text(framework.read_text() + "\n# changed runtime\n")
    runtime = bot.commit(repo, stamp, "runtime")
    assert bot.shared_changed(repo, runtime, index, {"search"})
    releases, distribution = bot.resolve(index, {"search": "patch"}, bot.mcp_plugins(repo, runtime, index))
    assert set(releases) == {"search"}
    notice = bot.shared_notice(repo, runtime, releases)
    assert "Shared runtime or dependency changes are included" in notice
    assert "`mhs`" in notice and "`edu-agent`" not in notice
    assert "all-mcp=patch" in notice
    assert bot.shared_notice(repo, runtime, {"edu-agent": "999.0.0"}) == ""

    class LocalAPI:
        repository = "owner/repo"
        body = ""

        def pages(self, path):
            return []

        def call(self, path, method="GET", data=None):
            if not path:
                return {"default_branch": "main", "clone_url": remote}
            if path == "pulls/7":
                return {
                    "base": {"ref": "main", "repo": {"full_name": self.repository}},
                    "head": {"ref": "source"},
                    "merged": True,
                    "merge_commit_sha": runtime,
                }
            assert path == "pulls" and method == "POST"
            self.body = data["body"]
            return {"html_url": "https://example.test/version-pr"}

    bot.git(repo, "push", remote, f"{runtime}:refs/heads/main")
    api = LocalAPI()
    reply = bot.make_release(api, repo, 7, {"id": 8}, {"search": "patch"}, None)
    assert notice in api.body and notice in reply
    bot.git(repo, "fetch", remote, f"refs/heads/{bot.branch_for(7, 8)}")
    after = json.loads(bot.at(repo, "FETCH_HEAD", "plugin-versions.json"))
    assert after["distribution_version"] == distribution
    assert {cap for cap in index["plugins"] if index["plugins"][cap] != after["plugins"][cap]} == {"search"}
    catalog_after = json.loads(bot.at(repo, "FETCH_HEAD", ".claude-plugin/marketplace.json"))
    for before, after_entry in zip(catalog["plugins"], catalog_after["plugins"], strict=True):
        if before["name"] != "qwen-mm-plugins-search":
            assert before == after_entry
    bot.git(repo, "checkout", "--detach", stamp)
    project = repo / "pyproject.toml"
    project.write_text(project.read_text() + "\n# changed dependencies\n")
    dependencies = bot.commit(repo, stamp, "dependencies")
    assert bot.shared_changed(repo, dependencies, index, {"search"})
