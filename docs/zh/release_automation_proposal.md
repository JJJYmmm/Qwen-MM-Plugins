# 发布自动化精简方案（审阅稿）

目标：代码正常合入 main，版本在发布时统一生成。main 中的安装引用始终指向已存在的稳定 tag。

建议保留现有单 Python 包结构，围绕一个发布 workflow、现有版本清单和版本生成脚本实现。

## 发布流程

流程分为两类独立 PR，功能开发和 bug 修复都采用同一规则：

| PR | 内容和职责 |
| --- | --- |
| 代码 PR | 提交代码、Skill、依赖及对应测试，正常合入 main；不要求同时递增发布版本或打 tag |
| 版本 PR | 决定发布时由 CI 单独生成，统一更新本批插件的版本、各 harness manifest/ref 和 distribution 版本；审核通过后由发布流程打 tag 并合并 |

一张版本 PR 可以汇总多个已合入的代码 PR。小改动可以留到下次，紧急 bug 修复也可以立即单独准备一次 patch 发布。

1. **选定发布内容。** 在代码 PR 下评论 `/release search=1.1.2 framework=1.1.10`。代码 PR 合并后，bot 从当时的 main 固定源码 SHA，生成独立的版本 PR；未选中的插件继续等待后续发布。共享 runtime 或依赖变化仅在版本 PR 中提示，不会扩大发布范围。
2. **生成版本 PR。** 在短期发布分支上运行现有版本生成脚本，生成只修改版本和 ref 的提交 R，并创建供审阅的版本 PR。同一批插件共享 R 和一个 distribution 版本。
3. **审核、验证并打 tag。** 审阅后在版本 PR 下评论 `/publish`，对准确提交 R 运行离线测试、manifest 检查及 wheel 构建；通过后原子推送本批插件 tag。已经存在的 tag 必须指向相同提交，绝不移动。
4. **合并同一张版本 PR。** 确认远端 tag 指向已验证的 R 后，以 merge commit 合入 main，让 R 保留在 main 历史中。安装入口随合并切换到新版，期间 main 上的其他代码由普通 Git 合并保留。发布后不再改写 R；合并发生冲突时停止自动合并，保留已发布 tag。该版本 PR 使用 merge commit，日常代码 PR 可以继续采用原有合并方式。

main 保留当前已发布 tag 的引用。本地开发继续使用现有 local 安装流程。

## Harness 兼容约束

发布自动化沿用现有安装接口：marketplace 地址、插件名称、目录结构、tag 命名、Python extra 和入口命令保持兼容；用户通过各 harness 原有的安装、更新和重载方式获取新版本。

- 保留 Claude、Codex、Qoder 三套 manifest 及 `.mcp.json` 的现有格式，统一生成版本和 ref，确保 Skill 和 MCP 对应同一个插件 tag。
- 沿用 CodeBuddy 的 marketplace 处理、OpenClaw 的本地 marketplace、Qwen Code 的 extension ref、Gemini 的 Skill tag checkout，以及手动注册流程。
- 安装器中的变更限于生成的版本清单；发布调度、影响范围计算和 tag 来源信息由 CI 消费。所有 harness 继续使用已经发布好的普通插件目录和 MCP 配置。
- 对发布快照和目录更新分别检查 manifest 一致性，并运行现有各 harness 安装、更新、local/restore 和手动配置回归。

已对 fork 目录更新核验：14 个已发布插件的 manifest 结构、名称、Skill 路径、MCP server key 和启动入口均保持一致；安装器除版本数组外字节一致。在隔离环境中运行现有安装器回归，54 项通过，覆盖七种受支持 harness 的安装/更新命令及 local/restore、手动配置等路径；manifest 一致性检查通过。该检查覆盖配置和安装命令接口，真实客户端的安装与激活仍需要按适配路径做冒烟验证。

## 版本和影响范围

| 项目 | 建议规则 |
| --- | --- |
| 单插件代码、Skill 或配置变化 | 将该插件列为待发布，本次是否发布由发布输入决定 |
| shared、MCP framework 或 pyproject.toml 变化 | 提示所选插件带入了共享变化，由发布者审阅兼容性并决定是否追加其他插件 |
| 普通文档、测试或生成的版本字段变化 | 不触发插件发布 |
| 插件版本 | CI 可建议下一个 patch；发布者可直接指定完整 SemVer，版本必须递增且不能覆盖已发布 tag |
| Python distribution 版本 | 每批发布递增一次，作为整个 Python 包的快照编号 |

发布范围由显式选择决定。即使修改 shared 或某个 extra，未选择的插件仍保留旧 ref 及其 framework 快照。
需要一起发布全部插件时使用 `/release all-plugins=patch framework=patch`，包括 Skill-only 插件，不含未发布模板；单独指定的插件版本可以覆盖批量级别。
只指定 framework/distribution 时要求补充插件选择。语义版本级别仍由发布者判断。

小改动可以先合入 main，在多次提交后一起发布。无需增加“暂缓发布”标签或状态文件：每次都与该插件上次发布的源码比较，待发布改动会自然保留。若希望发布同一插件的一部分改动，同时排除已经合入的另一部分，需要选择合适的源码提交或调整待发布代码；版本号本身不筛选改动。

## 只保留必要状态

- `plugin-versions.json` 记录安装目录当前推广的版本；其他 manifest 和安装器版本由脚本同步生成。
- 不新增 `.release/published.json` 或 `.release/snapshot.json`。新 tag 的注释记录 `Source-Commit`；tag 指向的提交提供源码、依赖声明和 distribution 版本。
- 现有 tag 没有 `Source-Commit` 时，直接使用 tag 对应的提交作为比较基线。比较时忽略生成的版本和引用字段。
- 一次处理一批发布。发现已发布但版本 PR 尚未合并的一批时，优先补齐该批；重试复用已有 tag 和版本 PR。CI 串行运行，避免并发分配版本。

失败恢复只有两个主要阶段：打 tag 前失败，修复后重新验证；打 tag 后失败，保留 tag 并重试合并同一张版本 PR。版本 PR 合入前，main 的安装入口继续使用旧版。

## 验证情况和边界

fork 原型已完成真实 tag 发布、wheel 构建、VCS 安装、MCP 初始化，以及两种 framework 快照共存验证。两个实验 PR 的 Linux/macOS CI 均通过。另已用两个真实实验 tag 验证：发布来源和 distribution 版本可从 tag 恢复；现有 search 稳定 tag 可直接作为旧版本基线。

上述完整 fork 验证对应较早的“独立快照再生成目录 PR”原型。当前“版本 PR 先打 tag 再 merge”的变体已完成本地 Git 流程验证：tag 发布时 main 仍引用旧版；合并后 R 进入 main 历史，tag 不变且保留期间的新代码。已核对上游和 fork 的合并设置允许 merge commit。

当前实现由一个 workflow、一个控制器和已有版本生成脚本组成，使用评论、PR 和 Git tag 保存状态。脚本支持精确版本、patch/minor/major、权限检查、PR 合并后处理请求，以及不可变 tag 重试。正式部署前需要将其放入默认分支并允许 Actions 创建 PR；本次只在 fork 隔离分支验证。

第三方依赖仍按 tag 内声明的范围解析；本方案没有实现传递依赖锁定。framework 随每个插件的快照安装；独立升级 framework 需要另外拆包。发布 tag 指向 R，随后通过 merge commit 将 R 纳入 main 历史；需要将现有文档中的“合并后打 tag”调整为这一发布顺序。

验证记录：[发布原型](https://github.com/JJJYmmm/Qwen-MM-Plugins/pull/1) · [目录更新实例](https://github.com/JJJYmmm/Qwen-MM-Plugins/pull/2) · [完整 fork 实验](https://github.com/JJJYmmm/Qwen-MM-Plugins/actions/runs/36626938026)
