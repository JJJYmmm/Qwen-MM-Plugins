# Hub authoring

Adding a plugin to the Hub has two parts:

1. Add the capability here using the [normal packaging convention](how_to_add_new_capability.md), including its version catalog entry, Skill, manifests, and server when applicable.
2. In [qwen-mm-plugins-hub](https://github.com/JJJYmmm/qwen-mm-plugins-hub), add `content/cookbooks/<cap>/usage.md` and case files under `public/cases/<cap>/<case>/`. Put media in that case's `assert/` directory. Optional cookbook front matter supplies category, tags, title and contributors.

The Hub discovers plugins, imports their actual MCP registries, counts tokens, and publishes automatically. No second plugin list, handwritten tool schema, or media inventory is needed. Cookbooks live only in the Hub; the README links directly to them.

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

## Branch and release

Hub builds read the upstream branch selected in the Hub's `source.config.json`; the site displays that branch and pins source links to its commit. A development branch such as `support_hub` can be previewed without merging main or publishing release tags. For source testing, check out that branch in a dedicated clone, then run Python from the checkout or use `bash install.sh local`; restore tracked manifests with `bash install.sh local --restore` before committing. The default installer still uses published releases, which require the normal [release process](releasing.md).
