# Release snapshot prototype

This prototype tests publishing immutable plugin snapshots before promoting their catalog refs.
It runs only on the fork's isolated `codex/release-snapshot-poc` branch and never updates `main`.

## What is being decoupled

| Item | Development | Published install |
|---|---|---|
| Capability code and Skill | Ordinary source commits; no mandatory version edit | Immutable capability tag |
| Plugin version | Last promoted version in the catalog | Version stamped in the release snapshot |
| MCP implementation | Current source checkout for local development | Same capability tag as the Skill/manifest |
| Python distribution/framework | Current source plus dependency declarations | Whole distribution at that capability tag |
| Third-party dependencies | Declared version ranges | Ranges frozen by tag; actual resolution remains time-dependent |
| Marketplace and installer | Latest promoted releases | Updated only after every new tag exists |

`mcp_framework.__version__` currently supplies the Python distribution version. It is a snapshot
identifier, not an independently released framework API version. Separate plugin versions do not
imply separate wheels: extras choose dependencies, and each wheel contains all packaged servers.
The existing per-tag `uvx --from` installs provide separate environments for the selected plugin.

## Publication order

1. Select an exact source commit and explicit SemVer release inputs.
2. Clone it into a temporary directory and run the existing version/ref preparation script there.
3. Record source SHA, dependency-declaration fingerprint, distribution version, and capability tags.
4. Commit the generated metadata on top of that source. Identical inputs produce the same commit.
5. Test/build this snapshot, then publish its annotated tags. Existing tags may only be reused when
   they resolve to the identical snapshot commit. Multiple new tags use one atomic push.
6. Verify the remote tag targets before preparing a catalog proposal from the *current* source.
7. Transform version/ref metadata only. Preserve newer source changes and `pyproject.toml` edits.
8. Review/merge the catalog proposal. Users keep installing the previous release until this point.

Release commits need not be merged back into development. In particular, squash/rebase merges do
not change the tested release commit. `.release/published.json` records each capability's original
source SHA so future planning does not depend on a generated tag commit being an ancestor of main.

The prototype keeps main-style MCP manifests pinned to the promoted release. Changing the source
manifests to `@main` is unnecessary for publication ordering; the existing `install.sh local`
workflow supplies a direct development install. Introducing remote development-channel manifests
later would require explicit development/release validation modes.

## Scope planning

`plan --base <bootstrap-source> --source <current-source>` compares a capability to its ledger's
last released source SHA, using the explicit bootstrap base for capabilities not yet in the ledger.
The bootstrap is an experiment fixture, not an automatically inferred production release baseline.
For migration, populate each capability's ledger from its actual current stable tag/source.

Capability/Skill changes affect that capability. Shared framework/base dependency/build/packaging
changes conservatively affect every MCP capability. Skill-only capabilities are excluded from
shared MCP runtime changes. Optional dependency changes follow capability extras, including
transitive self extras such as `core -> viz`. Version stamps and generated source refs are ignored.
SemVer level remains explicit; the planner only determines affected capabilities.

## Fork experiment

The workflow tests a first `search` snapshot and a later `mhs` snapshot with changed server source
and a narrower `msgpack` extra. Neither source change edits the release catalog. It builds both
wheels, publishes prerelease tags on the fork, installs the real VCS specs, initializes the MCP
servers, lists their tools without calling external APIs/hardware, and checks distribution/framework
versions. It then promotes both to an isolated catalog branch while preserving the later source
and dependency changes. Installing search again must still load its earlier framework snapshot.

Offline tests cover missing-tag rejection, immutable-tag conflicts, deterministic retries,
idempotent promotion, version regression, multiple capabilities, and shared/dependency scope.

Fork tags use fork URLs for the selected plugins. Manual installer experiments must set
`QMP_REPO=https://github.com/JJJYmmm/Qwen-MM-Plugins.git` and select only the experimental plugins;
the fork does not mirror the upstream's older stable tags. No harness install is performed here.

## Limits before production rollout

- Add production release inputs/scheduling, stable-tag ledger migration, and PR creation/merging.
- Require offline CI and wheel validation on each exact release snapshot before publishing.
- Use a production catalog concurrency lock; reject stale release plans instead of overwriting a
  newer plugin or distribution version. The prototype includes regression checks and serial CI.
- Decide whether to publish every shared-runtime consumer together or explicitly stage the rollout.
- Update the existing documented invariant that tags target the exact merged main commit.
- Keep the existing one-distribution packaging unless independent framework upgrade/downgrade is
  required. That stronger requirement needs a separate framework distribution and compatibility
  ranges, plus migration work for shared imports and base dependencies.
- `uvx --from` does not turn version ranges into a reproducible transitive dependency lock. A
  requirements lock would need to be consumed by the launcher (or use a separately distributed
  runtime environment). Merely adding a lockfile to the tag does not enforce it for this launch path.
- Stable release inputs must also yield a valid Python distribution version (PEP 440). The workflow
  uses SemVer `-rc.<number>` versions that normalize to `rc<number>` in wheel metadata.

See the fork workflow run and its job summary for actual evidence. This file describes a feasibility
prototype; it does not replace the existing stable installation/release instructions.
