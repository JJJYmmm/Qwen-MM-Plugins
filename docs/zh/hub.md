# Hub 文档与 docstring 工具说明

[Qwen MM Plugins Hub](https://jjjymmm.github.io/qwen-mm-plugins-hub/) 现在负责维护 cookbook、
case 页面、录屏和截图。请在 [Hub 仓库](https://github.com/JJJYmmm/qwen-mm-plugins-hub) 修改：

- `content/cookbooks/<cap>/usage.md`：唯一的 cookbook 正文。
- `public/cases/<cap>/<case>/index.html`：可选的交互案例页面。
- `public/cases/<cap>/<case>/assert/`：该案例的视频、截图及其他图片。

正文使用 `../../../public/cases/...` 相对路径，GitHub 可解析，Hub 构建时自动转换为站内地址。
不再另传 OSS，也不在插件仓库维护第二份正文；这里的 `cookbooks/` 只保留兼容跳转入口。
Skill 与工具定义仍在插件仓库维护。Hub 的插件目录仍读取远程 main，support_hub 不会自动合并 main。

## Docstring 作为说明来源

省略 `TOOL["description"]` 后，框架读取 `handle` 的 Google 风格 docstring：
开头正文成为工具说明，`Args:` 填补 Pydantic 字段缺失的描述。参数名写模型中的字段名，
不是包装函数接收的 `arguments` 字典。类型、默认值、枚举、约束和验证器仍由 Pydantic 提供。

没有 `Args:` 段时，整段清理缩进后的 docstring 就是工具说明；出现 `Args:` 时才启用结构化
Google 解析，`Returns:` 等辅助段落不会被追加到工具说明。

需要把示例等完整内容保留在模型可见说明里时，可设 `TOOL["docstring_format"] = "plain"`。
FreeCAD 的已有长示例使用该方式保留，参数描述仍在 Pydantic 字段里。

显式 `Field(description=...)` 优先；显式 `TOOL["description"]`（包括空字符串）保留旧逻辑，
支持动态说明，不解析函数 docstring。参数说明可以渐进迁移，字段名拼错或重复会在注册时直接报错。
示例见 [`example/echo.py`](../../src/capabilities/example/qwen_mm_plugins_example/tools/echo.py)
与[英文完整说明](../en/hub.md)。

## 切换与运行

`support_hub` 是开发分支，不等于已经发布的新插件版本。可以直接运行该 checkout 中的 Python，
或在专用 clone 中使用 `bash install.sh local`；它会把绝对路径写入 manifest，提交前用
`bash install.sh local --restore` 还原。发布元数据的更新不创建 tag；默认的 marketplace/tag
安装要等[合并和发布](releasing.md)后才会使用新代码。
