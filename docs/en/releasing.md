# Plugin releases

**English** · [中文](../zh/releasing.md)

Qwen-MM-Plugins publishes one Python distribution but versions each capability independently. A
capability release covers its Skill, manifests, MCP configuration, server code, and the shared code
visible at that tag.

## Version model

| Version | Scope | Source of truth |
|---|---|---|
| Plugin version | One capability | [`plugin-versions.json`](../../plugin-versions.json) → `plugins.<cap>` |
| Distribution version | Repository snapshot and shared Python distribution | `distribution_version` in the same file |
| Marketplace metadata version | Catalog snapshot; not a claim that every plugin changed | Distribution version |
| Plugin tag | Immutable source snapshot for one capability | `qwen-mm-plugins-<cap>-v<semver>` |

Marketplace entries and MCP `uvx --from` specs pin the same plugin tag. `main` is development-only.
Although a tag contains the whole distribution, each plugin launches its own tagged environment;
releasing `search` does not update an installed `core`.

Use SemVer per capability: patch for compatible fixes, minor for additive tools or behavior, and
major for breaking schemas, removed tools, or incompatible configuration. Review shared runtime changes
for compatibility with the selected capabilities; unselected capabilities keep their published snapshots
until explicitly released.

## Comment-driven releases

After the Release bot workflow is enabled on the default branch, code PRs can merge without version
bumps. When ready to release, a maintainer with repository write permission comments on a code PR:

```text
/release search=1.1.2 framework=1.1.10
```

Use exact versions or `patch`, `minor`, `major`; list multiple plugins with spaces. `framework` and
`mcp-framework` are aliases for `distribution`. This is the existing Python distribution version,
not a separately packaged framework. Omitting it defaults to the next distribution patch.

An open code PR's request waits for merge. On a merged PR, the bot immediately creates a separate
version PR from current main. It includes all accumulated code for the selected plugins, not only
the triggering PR. Shared runtime or `pyproject.toml` changes appear as a notice in the version PR;
they do not add other plugins to the release. Only explicitly selected plugins receive new versions.
Unselected plugins keep their published refs and framework snapshots. To expand an unpublished
release, close its version PR and submit a new request listing the additional plugins.

Use `/release all-plugins=patch framework=patch` to explicitly release every plugin listed in
`plugin-versions.json`, including Skill-only plugins such as `edu-agent`; unpublished templates are
excluded. Individual arguments override the batch level, e.g. `all-plugins=patch search=minor`.
Specifying only `framework`/`distribution` requires adding a plugin selection;
it never implicitly selects all plugins. Unpublished plugins require an explicit name and version;
`all-plugins` does not select them.

Review the generated version PR, then comment:

```text
/publish
```

The bot tests and builds that exact commit, publishes all plugin tags atomically, verifies their
remote targets, then merges the same PR **with a merge commit**. Thus main only starts referencing
the new tags after they exist, and the tagged commit becomes part of main history. Do not merge a
version PR manually before publication. Normal code PRs may still use squash or rebase merging.

Only one version PR is pending at a time. Duplicate requests reuse their PR. Existing tags must
point to the exact verified commit; they are never moved. If tag publication succeeded but the
merge failed, resolve required checks/reviews and retry `/publish` without changing the version PR
head. A content conflict requires closing it and preparing a new release with fresh version numbers;
retain the already-published tags. Other source PRs can continue merging during review.

### First release of a new plugin

Prepare the code, manifests, dependencies, and tests following [Add a new plugin](how_to_add_new_capability.md).
Keep template versions as placeholders; leave the published index, marketplace, and installer catalog unchanged.
A maintainer requests the first release on the code PR:

```text
/release new-plugin=1.0.0
```

After the code merges, the bot creates a version PR with the release versions, tag refs, and catalog
entries. Review it, then comment `/publish` to create the tag and merge the registration.

First releases require an exact version; subsequent releases also accept `patch`, `minor`, or `major`.
`all-plugins` selects published plugins only. Add an explicit selection to include a new plugin,
for example `/release all-plugins=patch new-plugin=1.0.0`. The `example` template is not published.

### Tag notes

Review **Tag notes preview** in the version PR before publishing. Each tag links to the version PR,
the PR that requested the release, and the included changes since that plugin's previous tag.
MCP shared runtime and dependency changes are listed separately for compatibility review;
commits without an associated PR keep their commit links.

First-release notes cover the plugin's development history and, for MCP plugins, its shared snapshot.
Published tags and their notes remain unchanged on retries.

### Repository setup

Keep `.github/workflows/release-bot.yml` and its scripts on the default branch. Allow Actions to
create pull requests under **Settings → Actions → General**, and enable merge commits for version
PRs. The workflow uses the built-in `GITHUB_TOKEN`; no bot account or additional secret is required.
Required reviews, status checks and repository rules still apply to publication and merging.

GitHub may require a maintainer to select **Approve workflows to run** on a bot-created version PR
before its ordinary PR checks start. Complete those checks and reviews before `/publish`.
See [GitHub's token event rules](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs).
The release workflow also independently tests the exact tagged commit with read-only permissions;
its write-enabled jobs run the controller from the default branch.

This automation does not change client installation protocols or publish to PyPI. The whole plugin
is installed from its tag, including its Skill, while MCP launch specs pin that same tag. Installing
a raw main plugin directory is a development path and can combine unreleased Skills with old MCP
refs; use the existing local mode for development.

## Legacy manual release checklist

The checklist below documents the existing manual workflow. The comment workflow above replaces
its merge-then-tag order and does not call the legacy tagging helper.

1. Prepare every affected capability on the PR branch:

   ```bash
   git fetch origin --tags --prune
   python3 scripts/prepare_plugin_release.py search 1.1.0 --distribution-version 1.0.2
   python3 scripts/check_manifests.py
   python3 -m pytest -m "not reachability" tests/
   ```

   The script updates release metadata and launch refs; it does not commit, tag, or push. When
   several capabilities share one release commit, prepare them with the same distribution version.

2. Commit the code and generated release metadata together, open the PR, and wait for it to merge.

3. Create the annotated tag on the exact commit now present on `origin/main`:

   ```bash
   python3 scripts/tag_plugin_release.py search
   git show qwen-mm-plugins-search-v1.1.0
   git push origin qwen-mm-plugins-search-v1.1.0
   ```

   The helper fetches `origin/main` and existing tags, verifies the release metadata and target tag
   are consistent, and builds the annotated message from non-merge commits that touched the
   capability since the previous capability tag, including cookbook history from before the Hub
   migration. It does not inspect commits in the separate Hub repository. It shows shared runtime
   commits separately for review; include a relevant one with `--include-shared <commit>`. Pass `--dry-run`
   to preview or `--push` to create and push in one step.

   Tagging after merge keeps releases on the main history even when GitHub uses squash or rebase
   merges. The helper refuses to replace a local or remote tag. Never move a published tag; issue a
   patch release instead.

4. Smoke-test the published tag using the [installation guide](installation.md).

## Hub documentation

Cookbooks and cases now live in [QwenLM/qwen-mm-plugins-hub](https://github.com/QwenLM/qwen-mm-plugins-hub).
Changes limited to that repository need a Hub deployment, not a plugin version bump. General
English guides stay in this repository and are imported when the Hub builds.

After a release or documentation update, the Hub detects changes to the branch selected by
`source.config.json`, normally plugin `main`, and its capability tags. Automatic publishing waits
until all tags referenced by the catalog exist. See [Publish and refresh](hub.md#publish-and-refresh)
for the scheduled fallback, optional immediate dispatch, and PR build checks.
Publishing the Hub never creates plugin tags or updates installed plugins.

## Release cadence

Batch ready changes roughly weekly, skip empty weeks, and release critical fixes when needed.
Multiple capability tags may point to the same merged commit. The `example` capability is a
development template and is not published.
