# Hub documentation and docstring-backed tools

The [Qwen MM Plugins Hub](https://jjjymmm.github.io/qwen-mm-plugins-hub/) owns cookbook prose,
case pages, recordings and screenshots. Edit them in
[`JJJYmmm/qwen-mm-plugins-hub`](https://github.com/JJJYmmm/qwen-mm-plugins-hub):

- `content/cookbooks/<cap>/usage.md`: the single editable cookbook source.
- `public/cases/<cap>/<case>/index.html`: an optional interactive case page.
- `public/cases/<cap>/<case>/assert/`: videos, screenshots and extracted case images.

Use relative links from the cookbook to `../../../public/cases/...`. They resolve in GitHub
and are converted into same-site URLs by the Hub build. Run the Hub's documented asset checks
after changing files. Do not upload another copy to OSS or duplicate cookbook prose here.
The small files under `cookbooks/` are compatibility links, not editable copies.

Skills and the actual tool definitions remain in this plugin repository. The Hub reads the
MCP registry rather than parsing a second website-specific definition. Its plugin snapshot
still follows upstream `main`; this branch prepares the code changes without merging main.

## Author descriptions once

Omit `TOOL["description"]` to derive the tool description from the `handle` docstring.
Google-style `Args:` entries document the fields of the Pydantic arguments model (not the
wrapper's single `arguments` dictionary):

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

Without an `Args:` section, the complete cleaned docstring is the public description.
With `Args:`, structured Google parsing uses introductory prose as the tool description and
fills missing field descriptions; `Returns:`, `Raises:` and examples are not appended.
Use `TOOL["docstring_format"] = "plain"` to keep the complete docstring, including any
`Args:`/examples, as the public description. The FreeCAD tools use this to preserve their
existing agent-facing examples. Their parameter descriptions remain in Pydantic fields.
Types, defaults, constraints and validators still come from Pydantic. Explicit field
descriptions win, and shared models are never modified in place. Unknown or duplicate
`Args:` field names fail registration to catch documentation typos.

An explicit `TOOL["description"]` preserves the original behavior, including explicit empty
strings and dynamic descriptions. Remove the key to opt in; otherwise handler docstrings
remain implementation documentation. Existing parameter descriptions can stay in `Field`
until individually migrated. The `example` echo tool demonstrates the all-docstring prose path.

## Trying the support branch

`support_hub` is a development branch, not an immutable plugin release. Run Python directly
from the checkout, or use `bash install.sh local` in a dedicated clone as described in
[local development](local_development.md). Local mode rewrites tracked manifests; restore
them with `bash install.sh local --restore` before committing. The prepared release metadata
does not create or publish tags. Marketplace/tag-pinned installs use the new code only after
the normal merge-and-release process in [releasing](releasing.md).
