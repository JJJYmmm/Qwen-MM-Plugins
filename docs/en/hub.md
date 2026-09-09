# Hub authoring

**English** · [中文](../zh/hub.md)

The Hub currently lives in **[QwenLM/qwen-mm-plugins-hub](https://github.com/QwenLM/qwen-mm-plugins-hub)**
and is published at [Qwen MM Plugins Hub](https://qwenlm.github.io/qwen-mm-plugins-hub/).
Start with [Add a new plugin](how_to_add_new_capability.md) to implement and register a capability.

Keep each kind of content in its owning repository:

| Content | Where to maintain it |
|---|---|
| Plugin summary | Capability manifests, marketplace description, and installer `CAP_DESC` in Qwen-MM-Plugins; the Hub reads the Codex manifest |
| Skill instructions and supporting files | `src/capabilities/<cap>/skill/` in Qwen-MM-Plugins |
| Tool and argument descriptions | Handler docstrings in Qwen-MM-Plugins; types and validation stay in Pydantic |
| General English guides | `docs/en/` in Qwen-MM-Plugins; the Hub imports them on each build |
| Cookbook, category, tags, title, contributors | `content/cookbooks/<cap>/usage.md` in the Hub |
| Demo videos, images, interactive cases | `public/cases/<cap>/<case>/` in the Hub |

The Hub discovers plugins from `plugin-versions.json`, reads their actual MCP registries and
Skills, and computes token estimates. Do not hand-edit generated `data/*.json`, maintain another
plugin list, or duplicate cookbooks in this repository.

## Author descriptions once

Every tool uses the same format: `TOOL` contains only `name` and `args`; `handle` has a Google-style docstring.

```python
from pydantic import BaseModel, Field


class EchoArgs(BaseModel):
    message: str
    repeat: int = Field(default=1, ge=1, le=10)


TOOL = {"name": "echo", "args": EchoArgs}


def handle(arguments: dict) -> list[dict]:
    """Echo text back to the caller.

    Args:
        message: Text to repeat.
        repeat: Number of repetitions, from 1 to 10.
    """
    return [{"type": "text", "text": arguments["message"] * arguments.get("repeat", 1)}]
```

Write the tool's purpose in the introductory prose. Document every argument exactly once under `Args:`, including inherited fields. Put nested object details in their argument description. Optional `Examples:` content is included in the public tool description. Zero-argument tools do not need `Args:`.

Types, defaults, aliases, constraints and validators belong in Pydantic; prose belongs in docstrings. There are no explicit-description overrides or format switches. Registration rejects missing/duplicate argument documentation. The same enriched schema reaches both FastMCP and the Hub exporter without mutating the original model.

For a Skill, use its frontmatter `description` to say when to use it and what it does. Give it a
task-specific H1 instead of repeating the repository name. Keep supporting scripts, references,
and assets under `skill/`; the Hub links their tracked file hierarchy and shows the first 50
lines of `SKILL.md`, expandable to the full text. Do not shorten the source just for the preview.

## Cookbook and cases

Create `content/cookbooks/<cap>/usage.md` in the Hub. This file is required for every registered
plugin; its YAML metadata is optional. For example, a `my-plugin` cookbook can start with:

```markdown
---
title: My Plugin
category: Understanding
tags: [image, video]
contributors: [QwenLM]
order: 10
---

# My Plugin

## Workflow

Describe the input, setup, steps, and expected result.

## Cases

[Demo](../../../public/cases/my-plugin/demo/assert/demo.mp4)

[Interactive case](../../../public/cases/my-plugin/demo/index.html)
```

Contributors are GitHub account names, not URLs; their profiles and avatars are derived
automatically. They default to `QwenLM`. Prefer one or two useful task/modality tags. Without
metadata, the title comes from the capability ID, category is `Other`, and order is `99`.

Keep each case self-contained:

```text
public/cases/my-plugin/demo/
├── index.html          # optional interactive case
└── assert/
    ├── demo.mp4
    ├── screenshot.png
    └── ...             # other files used by this case
```

Use the existing directory name **`assert`**, not `assets`. Put a video or HTML link in its own
paragraph, as above: the Hub replaces it with a player or sandboxed iframe. Inline links remain
links; images use normal Markdown image syntax. Do not add a duplicate thumbnail, “view
recording,” or download prompt beside the embed. Use relative `assert/...` URLs inside the HTML
case. Cookbook paths are rewritten for the website, so no separate public media host is needed.

For video, use MP4 with H.264/YUV420P, AAC audio if present, and faststart. Keep every case file
below 25 MiB, the Hub's current build limit. Commit actual files, not symlinks or Git LFS pointer
files. Review recordings for credentials, personal data, and sharing rights before committing.

## Validate locally

Use Node 24 and Python 3.12+. From a parent directory, create sibling checkouts if needed:

```bash
git clone --branch support_hub https://github.com/QwenLM/Qwen-MM-Plugins.git
git clone https://github.com/QwenLM/qwen-mm-plugins-hub.git
cd qwen-mm-plugins-hub
npm ci
python3 -m venv .venv
.venv/bin/pip install -e '../Qwen-MM-Plugins[omni-memory]' -r scripts/requirements-export.txt
.venv/bin/python -m scripts.build_content --source ../Qwen-MM-Plugins
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
npm test
SITE_BASE_PATH=/qwen-mm-plugins-hub npm run build
```

For existing clones, use their paths instead. Commit the plugin changes first and keep the
source checkout clean: documentation and file links refer to the committed snapshot. Its HEAD
must match the branch in the Hub's `source.config.json`. Use `npm run dev` for local preview;
omit `SITE_BASE_PATH` for a root-domain production build. Frontend-only edits can use the already
generated data without Python.

## Publish and refresh

1. Push or merge the plugin-side changes into the remote branch selected in the Hub's
   [`source.config.json`](https://github.com/QwenLM/qwen-mm-plugins-hub/blob/main/source.config.json),
   currently `support_hub`, before triggering the Hub build. A local commit or an unmerged PR
   is not enough. For a new plugin, prepare its Hub cookbook alongside that change so the next
   Hub build has both halves.
2. Push or merge the cookbook and case files into Hub `main`. That push runs
   [Build and deploy plugin directory](https://github.com/QwenLM/qwen-mm-plugins-hub/actions/workflows/pages.yml).
   If only plugin source, descriptions, or `docs/en/` changed, run that workflow manually on Hub
   `main` using **Run workflow**. A push to Qwen-MM-Plugins alone does not trigger it.
3. Wait for the build and deployment to pass, then check the plugin, cookbook, and Docs pages on
   [the public Hub](https://qwenlm.github.io/qwen-mm-plugins-hub/). Builds regenerate the catalog,
   cookbooks, English docs, and token estimates together. Failed builds leave the published site
   unchanged; fix the reported issue and rerun.

Keep English guides in this repository, not a second Hub docs folder. Each `docs/en/**/*.md`
needs an H1 title and a unique route: underscores become hyphens, and nested path segments are
joined with hyphens. Relative links between imported English guides stay inside the Hub.

## Branch and release

The page displays the configured source branch and pins source links to its commit. Publishing
`support_hub` documentation does not merge plugin `main` or publish release tags. The default
installer still uses published releases, which may differ from the preview. Test branch code
through the [local-development workflow](local_development.md), not an unpublished release tag.

After the prepared changes merge into plugin `main`, set `ref` to `main` in the Hub's
`source.config.json` and rebuild. Plugin distribution still follows the independent
[release process](releasing.md); cookbook and case-only edits need only a Hub deployment.
