# Hub 维护

[English](../en/hub.md) · **中文**

Hub 当前维护在 **[QwenLM/qwen-mm-plugins-hub](https://github.com/QwenLM/qwen-mm-plugins-hub)**，发布地址是 [Qwen MM Plugins Hub](https://jjjymmm.github.io/qwen-mm-plugins-hub/)。实现和注册能力从[添加新插件](how_to_add_new_capability.md)开始。

仓库迁移期间，公开网址暂时不变。从官方仓库部署前，需要管理员启用 **Settings → Pages → Source: GitHub Actions**。首次部署成功后，再将公开链接更新为工作流返回的网址。

按内容归属维护：

| 内容 | 维护位置 |
|---|---|
| 插件简介 | Qwen-MM-Plugins 的能力 manifest、marketplace description 和安装器 `CAP_DESC`；Hub 读取 Codex manifest |
| Skill 指令及支持文件 | Qwen-MM-Plugins 的 `src/capabilities/<cap>/skill/` |
| 工具和参数说明 | Qwen-MM-Plugins 的 handler docstring；类型与校验仍在 Pydantic |
| 通用英文文档 | Qwen-MM-Plugins 的 `docs/en/`，每次 Hub 构建自动导入 |
| Cookbook、分类、tag、标题、contributor | Hub 的 `content/cookbooks/<cap>/usage.md` |
| 演示视频、图片、交互 case | Hub 的 `public/cases/<cap>/<case>/` |

Hub 从 `plugin-versions.json` 发现插件，读取真实 MCP registry 和 Skill，再计算 token。不要手改生成的 `data/*.json`、增加第二份插件表，或把 cookbook 复制回本仓库。

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

Skill 的 frontmatter `description` 说明何时使用、能完成什么；H1 使用具体任务名称，不重复仓库名。脚本、参考资料和素材保留在 `skill/` 下，Hub 展示 tracked 文件层级并链接源码；`SKILL.md` 默认预览前 50 行，可展开全文，不必为预览而删减源文件。

## Cookbook 与 case

在 Hub 创建 `content/cookbooks/<cap>/usage.md`。每个已注册插件都必须有该文件，YAML metadata 可选。以 `my-plugin` 为例：

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

Contributors 写 GitHub 账号名，不写 URL；头像和主页链接自动生成，默认 `QwenLM`。Tag 优先保留一两个有用的任务/模态标签。不填 metadata 时，标题从能力 ID 生成，分类为 `Other`，排序值为 `99`。

每个 case 独立存放所需文件：

```text
public/cases/my-plugin/demo/
├── index.html          # 可选的交互页面
└── assert/
    ├── demo.mp4
    ├── screenshot.png
    └── ...             # 此 case 使用的其他文件
```

沿用目录名 **`assert`**，不是 `assets`。像模板一样把视频或 HTML 链接单独放在一个段落，Hub 会替换为播放器或隔离的 iframe；正文中的行内链接仍是链接，图片使用普通 Markdown 图片语法。不要在内嵌预览旁重复放缩略图、“查看录屏”或下载提示。HTML 内用相对的 `assert/...` 路径引用文件，cookbook 路径会自动转换成网站地址，不需要另外托管公网媒体链接。

视频使用 H.264/YUV420P 的 MP4，有音轨时用 AAC，并启用 faststart。每个 case 文件应小于 25 MiB，这是 Hub 当前的构建限制。提交实际文件，不要提交符号链接或 Git LFS pointer。提交前检查录屏中的凭证、个人信息和素材分享权限。

## 本地验证

使用 Node 24 和 Python 3.12+。需要新建环境时，在同一父目录创建两个相邻 clone：

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

已有 clone 时使用实际路径即可。先提交插件侧修改并保持源 checkout 干净：文档和文件链接绑定到已提交快照，HEAD 必须对应 Hub `source.config.json` 指定的分支。`npm run dev` 用于本地预览；根域名发布时不设置 `SITE_BASE_PATH`。仅改前端可直接使用已有生成数据，无需运行 Python。

## 发布与刷新

1. 先将插件側修改 push 或合并到 Hub [`source.config.json`](https://github.com/QwenLM/qwen-mm-plugins-hub/blob/main/source.config.json) 指定的远程分支，当前为 `support_hub`，再触发 Hub 构建；只有本地 commit 或未合并的 PR 不够。新增插件时同时准备好 Hub cookbook，确保下一次构建能拿到两边内容。
2. 将 cookbook 和 case 文件 push 或合并到 Hub `main`，该 push 会触发 [Build and deploy plugin directory](https://github.com/QwenLM/qwen-mm-plugins-hub/actions/workflows/pages.yml)。如果只改了插件源码、description 或 `docs/en/`，在 Hub `main` 上通过 **Run workflow** 手动运行该工作流。只向 Qwen-MM-Plugins push 不会自动触发它。
3. 等构建和部署通过，再检查[公网 Hub](https://jjjymmm.github.io/qwen-mm-plugins-hub/) 的插件、cookbook 和 Docs 页面。构建会统一刷新目录、cookbook、英文文档和 token 估计；失败时线上内容不变，修复错误后重新运行。

英文指南继续维护在本仓库，不另建 Hub docs 正文。每份 `docs/en/**/*.md` 都要有 H1 标题和唯一的路由：文件名下划线转成连字符，嵌套目录也用连字符连接。英文指南间的相对链接在 Hub 内跳转。

## 分支与发布

页面显示所选源码分支，源码链接固定到对应 commit。发布 `support_hub` 文档不会合并插件 `main` 或发布 tag；默认安装器仍使用正式发布版本，可能与预览不同。分支代码按[本地开发流程](local_development.md)测试，不要使用尚未发布的 release tag 安装。

准备好的修改合入插件 `main` 后，把 Hub `source.config.json` 的 `ref` 改为 `main` 再构建。插件分发仍遵循独立的[发布流程](releasing.md)；仅修改 cookbook 和 case 时，只需发布 Hub。
