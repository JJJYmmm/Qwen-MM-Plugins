# 插件发布

[English](../en/releasing.md) · **中文**

Qwen-MM-Plugins 只发布一个 Python distribution，但每个能力独立管理版本。一次能力发布包含该
能力的 Skill、manifest、MCP 配置、server 代码，以及该 tag 可见的共享代码。

## 版本模型

| 版本 | 范围 | 唯一来源 |
|---|---|---|
| 插件版本 | 单个能力 | [`plugin-versions.json`](../../plugin-versions.json) → `plugins.<cap>` |
| Distribution 版本 | 仓库快照和共享 Python distribution | 同一文件中的 `distribution_version` |
| Marketplace metadata 版本 | 目录快照；不表示所有插件都发生变化 | Distribution 版本 |
| 插件 tag | 单个能力使用的不可变源码快照 | `qwen-mm-plugins-<cap>-v<semver>` |

Marketplace entry 与 MCP `uvx --from` 固定到同一个插件 tag；`main` 只用于开发。虽然每个 tag
都包含完整 distribution，但各插件启动独立的 tag 环境；发布 `search` 不会更新已安装的 `core`。

每个能力遵循 SemVer：兼容修复增加 patch，新增工具或兼容行为增加 minor，破坏 schema、删除工具
或不兼容配置增加 major。共享 runtime 变化需要审阅所选能力的兼容性；未选择的能力继续使用原有发布快照，
等显式选择后再发布。

## 评论触发发布

默认分支启用 Release bot 后，代码 PR 可以正常合入而不修改版本号。决定发布时，有仓库写权限的维护者
在代码 PR 下评论：

```text
/release search=1.1.2 framework=1.1.10
```

插件可以指定完整版本或 `patch`、`minor`、`major`；多个插件用空格分隔。`framework` 和
`mcp-framework` 都是 `distribution` 的别名，指当前 Python distribution 的版本，不是单独拆包的
framework 版本。省略时自动增加 distribution patch。

代码 PR 尚未合并时先登记，合并后再生成独立的版本 PR；已合并时立即生成。源码取当时 main 的完整快照，
所选插件包含累计改动，不仅是触发评论所在 PR 的改动。检测到 shared、framework 或 `pyproject.toml`
变化时，在版本 PR 中提示，由发布者决定范围；仅显式指定的插件更新版本。其他插件保留原有 ref 和 framework
快照。想扩大尚未发布的范围时，关闭当前版本 PR，再提交包含额外插件的新指令。

需要一起发布全部插件时，显式使用 `/release all-plugins=patch framework=patch`，范围是
`plugin-versions.json` 列出的全部插件，包括 `edu-agent` 等 Skill-only 插件，不含未发布模板。
单插件参数可以覆盖批量级别，例如 `all-plugins=patch search=minor`。只指定 framework/distribution
时会要求补充插件选择，不会默认选择全部。未发布插件必须显式指定名称和版本，`all-plugins` 不会自动选中它们。

审阅 bot 生成的版本 PR 后，在该 PR 下评论：

```text
/publish
```

bot 对准确的版本提交运行测试并构建 wheel，原子推送本批插件 tag，确认远端 tag 后，以 **merge commit**
合并同一张版本 PR。因此 main 切换安装引用时 tag 已经存在，打 tag 的提交也会进入 main 历史。请勿在发布前
手动合并版本 PR。普通代码 PR 仍可 squash/rebase。

一次只处理一张待完成的版本 PR，重复指令复用已有 PR。tag 已存在时必须指向相同提交，绝不移动。若 tag
已发布但合并失败，补齐审核或检查后重新评论 `/publish`，保持版本 PR 的 head 不变。如果是内容冲突，关闭
该版本 PR，用新的版本号重新准备；保留已经发布的 tag。其他代码 PR 在此期间仍可正常合入。

### 新插件的首次发布

按[新增插件](how_to_add_new_capability.md)准备代码、manifest、依赖和测试，保留模板版本作为占位值，
不修改版本索引、marketplace 或安装器的插件列表。维护者在代码 PR 下请求首发：

```text
/release new-plugin=1.0.0
```

代码合并后，bot 创建版本 PR，填写正式版本、tag 引用和目录条目。审阅后在版本 PR 下评论
`/publish`，由 bot 先打 tag，再合并上架信息。

首发必须指定完整版本，后续更新也可使用 `patch`、`minor`、`major`。`all-plugins` 只选择已发布插件；
可以显式追加新插件，例如 `/release all-plugins=patch new-plugin=1.0.0`。`example` 模板不发布。

### Tag 发布说明

发布前审阅版本 PR 中的 **Tag notes preview**。每个 tag 包含版本 PR、触发发布的 PR，以及该插件
自上个 tag 以来的改动。MCP 共享 runtime 和依赖改动单独列出，供兼容性审阅；没有关联 PR 的提交
保留 commit 链接。

首发说明包含插件的开发历史，MCP 插件另记录所用共享快照。已发布 tag 及其说明在重试时保持不变。

### 仓库设置

将 `.github/workflows/release-bot.yml` 及其脚本放在默认分支，在 **Settings → Actions → General**
允许 Actions 创建 PR，并为版本 PR 开启 merge commit。流程使用内置 `GITHUB_TOKEN`，无需额外 bot
账号或 secret。发布与合并仍受仓库规则、必需审核和状态检查约束。

GitHub 可能要求维护者先在 bot 创建的版本 PR 中点击 **Approve workflows to run**，普通 PR 检查才会
开始。完成这些检查和审核后再评论 `/publish`。见
[GitHub token 事件规则](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs)。
发布流程还会以只读权限独立验证实际打 tag 的提交；持有写权限的任务只运行默认分支的控制器。

此流程沿用各 harness 的安装接口，不向 PyPI 发布。插件整体从 tag 获取 Skill，MCP 也固定到同一个 tag。
直接安装 main 的原始插件目录可能混用未发布 Skill 和旧 MCP；开发请使用已有 local 模式。

## 原有手动发布清单

以下保留现有手工操作说明。上面的评论流程替代其“先合并、后打 tag”顺序，不调用旧的打 tag 脚本。

1. 在 PR 分支准备所有受影响的能力：

   ```bash
   git fetch origin --tags --prune
   python3 scripts/prepare_plugin_release.py search 1.1.0 --distribution-version 1.0.2
   python3 scripts/check_manifests.py
   python3 -m pytest -m "not reachability" tests/
   ```

   脚本会更新发布元数据和启动 ref，但不会 commit、tag 或 push。多个能力共用一个发布 commit
   时，应使用相同的 distribution version。

2. 将代码与生成的发布元数据放在同一 commit，创建 PR，并等待合并。

3. 在 `origin/main` 当前实际存在的 commit 上创建 annotated tag：

   ```bash
   python3 scripts/tag_plugin_release.py search
   git show qwen-mm-plugins-search-v1.1.0
   git push origin qwen-mm-plugins-search-v1.1.0
   ```

   该脚本会拉取 `origin/main` 和现有 tags，检查发布元数据与目标 tag 是否一致，并把自上一个
   capability tag 以来、实际修改该 capability 的非 merge commits（包括迁移到 Hub 前的 cookbook 历史）写入 tag
   message；它不读取独立 Hub 仓库的提交。shared runtime commits 会单独列出供人工判断；确认相关时使用
   `--include-shared <commit>` 纳入说明。使用 `--dry-run` 预览，或使用 `--push` 一次完成创建和
   推送。

   合并后再打 tag，可以避免 GitHub squash/rebase 导致 tag 脱离主线。脚本会拒绝覆盖本地或
   远端已有 tag。已发布 tag 不得移动；发现问题时发布新的 patch 版本。

4. 按[安装文档](installation.md)对公开 tag 做 smoke test。

## Hub 文档

Cookbook 和 case 已迁入 [QwenLM/qwen-mm-plugins-hub](https://github.com/QwenLM/qwen-mm-plugins-hub)。只修改该仓库时需要部署 Hub，不需要提升插件版本。通用英文文档仍在本仓库维护，由 Hub 构建时导入。

发布插件或修改文档后，Hub 自动检测 `source.config.json` 选定分支（通常为插件 `main`）及能力 tag 的变化；目录引用的 tag 全部存在后才自动发布。定时兜底、可选的即时触发和 PR 构建检查见[发布与刷新](hub.md#发布与刷新)。发布 Hub 不会创建插件 tag，也不会更新已安装插件。

## 发布周期

准备好的常规改动大约每周批量发布；空周不发，关键修复按需发布。多个能力 tag 可以指向同一个
合并 commit。`example` 是开发模板，不对外发布。
