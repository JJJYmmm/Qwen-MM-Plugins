# Hub 维护

新增插件只涉及两处：

1. 在本仓库按[正常插件结构](how_to_add_new_capability.md)实现能力，包括版本目录、Skill、manifest，以及需要时的 MCP server。
2. 在 [qwen-mm-plugins-hub](https://github.com/JJJYmmm/qwen-mm-plugins-hub) 添加 `content/cookbooks/<cap>/usage.md`，把 case 放在 `public/cases/<cap>/<case>/`，媒体放在 case 的 `assert/` 下。分类、tag、标题和 contributor 可直接写在 Cookbook 顶部的 YAML front matter。

Hub 自动发现插件、读取真实 MCP registry、计算 token 并发布。不需要额外的插件登记表、手写工具 schema 或素材清单。Cookbook 只维护在 Hub，本仓库 README 直接链接过去。

## 唯一工具约定

所有工具统一：`TOOL` 只包含 `name`、`args`，工具说明和参数说明写在 `handle` 的 Google-style docstring 中。

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

开头写工具用途；`Args:` 为每个参数写一条说明，包括继承字段，不能遗漏或重复。嵌套对象的内部字段写在对应参数说明中。可选的 `Examples:` 会保留在公开工具说明里。无参数工具不需要 `Args:`。

Pydantic 只负责类型、默认值、别名、约束和 validator，说明只写在 docstring。不再提供显式 description 覆盖或格式开关。框架生成的同一份 schema 同时供 FastMCP 和 Hub 使用，不修改原始模型。

## 分支与发布

线上 Hub 从远程 main 构建。`support_hub` 只准备修改，不合并 main、不发布标签。本地可直接从源码运行 Python，或在独立 clone 中用 `bash install.sh local`；提交前运行 `bash install.sh local --restore` 恢复 manifest。按 tag 安装的插件需要走正常[发布流程](releasing.md)才会更新。
