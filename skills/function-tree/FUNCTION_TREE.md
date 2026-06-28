# FUNCTION_TREE

> 本文件是 `function-tree` skill 自身的功能树与状态注册表——用 skill 自己的方法论描述 skill 自己。
> 用 `ft-governance.cjs doc` 在任何被治理的仓库里刷新业务项目的 `FUNCTION_TREE.md`；本文件描述 skill 的能力地图。
> 维护规则：当 `scripts/ft-governance.cjs` 或 `lib/commands-*.cjs` 增删命令时，同步更新 §3 命令清单与 §5 文件契约。

## 1. 项目定位

- **名称**：function-tree（功能树治理 skill）
- **形态**：Claude Code Skill（`/ft:*` 触发）+ 确定性 Node.js 助手（`ft-governance.cjs`）
- **一句话**：把"功能/能力"作为项目主线，用状态机 + 证据 + 授权闸门，把"声明做了/代码做了/打算做"统一登记到一棵可治理的树里，防止方向漂移与未授权改动。
- **设计原则**：
  - 功能为主线，模块/命令/证据/依赖挂接在功能节点下
  - 状态机为硬约束：未授权不许动源码；证据 `HEAD` 与当前 `HEAD` 不一致则标记 stale
  - 治理事实只信 JSON + git diff，不信 issue/PR
  - 生成的 markdown 不手改；改 JSON → `sync` → `doc`

## 2. 功能全景图

| 能力域 | 当前状态 | 说明 |
|---|---|---|
| 项目初始化 | 已实现 | `init` 自动发现 README、源码、API 路由、TODO、entrypoint、CHANGELOG 等候选 |
| 功能树文档 | 已实现 | `doc` 生成/刷新仓库根 `FUNCTION_TREE.md`，保留 project-notes 区块 |
| 节点生命周期 | 已实现 | planning → prepared → authorized → implementation → closed-out，`transition` 强制合法路径 |
| 证据收集 | 已实现 | `observe` 把证据路径/笔记与当前 `HEAD` 绑定 |
| 授权闸门 | 已实现 | `authorize` 生成任务卡 + `--allowed`/`--non-goal`/`--commit-gate`/`--closeout-gate` |
| 收尾 | 已实现 | `closeout` 写入落地点、兼容性、通过的 gate |
| 主线分层（Phase 1） | 已实现 | track=mainline/backlog/optimize/untracked + depth 0/1/2/99 + mainline_id |
| 主线强制（Phase 2） | 已实现 | `validate full` 触发 V-MAINLINE-UNIQUE / ORPHAN / BACKLOG-LOCK / DEPTH-MISMATCH |
| 漂移检测（Phase 2） | 已实现 | `drift-check --files/--staged`，UNTRACKED → exit 1 |
| 漂移接受（Phase 3） | 已实现 | `accept-drift` 时间盒豁免，mainline 切换自动失效 |
| 钩子集成（Phase 4） | 已实现 | `install-guard` 装 git pre-commit；`pre-edit` 输出 Claude Code hook JSON；`session-start` 注入会话上下文 |
| 治理配置 | 已实现 | `config` 读写 `drift_check_mode` / `hooks_mode` / `mainline_warning` / `auto_accept_suggest` |
| 跨工具责任契约 | 已实现 | `steward-sync` 派生 `steward/` 索引（current-next-gates / evidence-index / tracks/） |
| 自动发现盲区 | 已实现 | 6 个 promote-* 命令分别覆盖 pkg / README / entrypoint / git untracked / CHANGELOG |
| 候选评审 | 已实现 | `suggest-nodes` dry-run 打印草稿，`--yes` 批量导入 |

## 3. 命令清单（与 `ft-governance.cjs --help` 对齐）

> 调用形如 `node $SKILL_DIR/scripts/ft-governance.cjs <command> [args] [--root <repo>]`。
> 在 Claude Code 内通过 `/ft:<command>` 触发；本表列出全部 40 条命令。

### 3.1 初始化与文档

| 命令 | 作用 |
|---|---|
| `init [<program>] [--ref <node>] [--description <text>] [--no-doc]` | 创建 `.governance/programs/<program>/`、active gate 文件、根 `FUNCTION_TREE.md`；候选来自 README/entrypoint/源码/TODO/UI/API/OpenAPI/命令示例 |
| `doc` | 刷新根 `FUNCTION_TREE.md`，保留 project-notes 与手维护的功能树主体 |

### 3.2 节点创建与重塑

| 命令 | 作用 |
|---|---|
| `new-node <program> <id> --title <t> --ref <r> [--type <kind>] [--owner-lane <lane>] [--parent <id>] [--freshness <p>] [--track <mainline\|backlog\|optimize\|untracked>] [--mainline-id <id>] [--depth <0\|1\|2\|99>]` | 加 planning 节点与 active gate |
| `new-node-batch <program> --from-dirs <dir> [--id-prefix <t>] [--pattern <glob>] [--parent <id>] [--track <t>] [--mainline-id <id>] [--depth <n>] [--type <kind>] [--dry-run]` | 遍历 `<dir>` 一层，每个子目录产出一个节点（批量） |
| `reparent <program> <id> --parent <id> [--mainline-id <id>] [--depth <n>] [--track <t>]` | 原子地重设父节点，修复 parallel-mainline 违规（无需手改 nodes.json） |
| `suggest-nodes <program> [--yes] [--dry-run]` | 把自动发现的候选拟成节点草稿；README → mainline depth 0，路由/模型簇 → backlog depth 1 |
| `promote-pkgs <program> [--yes] [--dry-run]` | 盲区 A：pkg 根一级子包提升为节点（识别 `__init__.py` / `package.json` / `Cargo.toml` / `go.mod`） |
| `promote-readme <program> [--yes] [--dry-run]` | 盲区 B：README H2/H3 提升为 mainline 节点；锚点尽量解析为文件证据 |
| `promote-entrypoints <program> [--yes] [--dry-run]` | 盲区 C：manifest entry-points（`[project.scripts]` / `bin` / `[[bin]]`）；双重证据（manifest + 目标文件定义符号）落 mainline |
| `promote-untracked <program> [--yes] [--dry-run]` | 盲区 D：git 工作区 `??`/`A` 文件 → backlog `待实现` 节点（最强开工信号） |
| `promote-changelog <program> [--yes] [--dry-run]` | E5：CHANGELOG 发布要点（Markdown `## x.y.z` 或 RST `Version x.y.z`）→ mainline `声明实现` 节点 |

### 3.3 生命周期闸门

| 命令 | 作用 |
|---|---|
| `observe <program> <id> --evidence <path-or-note> [--kind <k>] [--note <t>]` | 记录证据并绑定当前 `HEAD`；源码仍未授权 |
| `authorize <program> <id> --allowed <p> --non-goal <t> --commit-gate <t> --closeout-gate <t>` | 生成 scope/non-goals/acceptance gates + 任务卡；推到 `authorized` |
| `transition <program> <id> --to <status> [--note <t>] [--blocker <t>] [--unblock-target-state <s>]` | 在合法状态间推进；阻断陈旧的 implementation 批准 |
| `closeout <program> <id> --summary <path-or-note> [--compatibility <t>] [--gate <t>]` | 写入落地点、兼容性、通过的 gate |
| `scope-check [--files a,b,c]` | 确认编辑仍在 active authorization 范围内（PostToolUse 用） |

### 3.4 查询与可视化

| 命令 | 作用 |
|---|---|
| `status` | 汇总治理程序与 active gate |
| `gate [--verbose]` | 显示当前阻塞与下一步允许动作 |
| `mainline` | 打印 active mainline 树（depth 0 根 + 1/2 子 + backlog + switch-lock 状态） |
| `locate <file>` | 通过 `.governance/file-to-track.json` 反查文件所属 track |
| `map` | 重建 file→track 反向索引并打印覆盖统计 |
| `validate [full] [--steward]` | 校验状态机；`full` 触发主线规则（V-MAINLINE-* / V-BACKLOG-LOCK / V-DEPTH-MISMATCH / V-ACCEPTANCE-*） |

### 3.5 漂移检测与豁免

| 命令 | 作用 |
|---|---|
| `drift-check --files <a,b,c> \| --staged` | 严格漂移检测；exit 0=全 mainline，1=有 UNTRACKED，2=参数错 |
| `accept-drift --reason <t> --files <a,b,c> [--expires <spec>] [--mainline <id\|none>] [--by <name>]` | 时间盒豁免；默认 30d，`0`=永久，格式 `<N><s\|m\|h\|d\|w>` |
| `revoke-drift --id <id>` | 把豁免标记为 `revoked`（保留审计记录） |

### 3.6 钩子与配置

| 命令 | 作用 |
|---|---|
| `install-guard [--force]` | 写 `.governance/guards/{ft-scope-check.sh, pre-commit}`，打印 hook 接入片段 |
| `session-start` | Phase 4：打印会话上下文（active mainline + 子代、漂移计数、active 豁免与最近到期、下一步 gate 建议） |
| `pre-edit --files <a,b,c>` | Phase 4：PreToolUse 用，输出 Claude Code hook JSON `{decision:"approve"\|"block", reason, context}` |
| `config [list\|get\|set] [--key <k>] [--value <v>]` | 读写 `.governance/config.json`：`drift_check_mode` / `hooks_mode` / `mainline_warning` / `auto_accept_suggest`；env `FT_DRIFT_CHECK_MODE` / `FT_HOOKS_MODE` / `FT_MAINLINE_WARNING` / `FT_AUTO_ACCEPT_SUGGEST` 覆盖文件值 |

### 3.7 维护

| 命令 | 作用 |
|---|---|
| `sync` | 从 nodes 刷新 active gates markdown |
| `steward-sync` | 派生 `.governance/steward/`（steward-index / current-next-gates / evidence-index / tracks/） |
| `repair` | 从 program nodes 重建 active gates 并丢弃 closed/archived gates |

## 4. 状态机（精简版）

详见 `references/STATE_MACHINE.md`。

```
planning ──(new-node)──► prepared
prepared ──(observe)──► evidence-prepared
evidence-prepared ──(decide)──► decision-prepared
decision-prepared ──(authorize)──► authorization-prepared
authorization-prepared ──(scope defined)──► authorized
authorized ──(implementation)──► implementation
implementation ──(closeout)──► closed-out
```

任意节点可被阻断：`transition --blocker <text> --unblock-target-state <status>`。

## 5. 文件契约（治理侧）

| 文件 | 谁写 | 用途 |
|---|---|---|
| `.governance/active-gates.json` | helper | 当前生效闸门 |
| `.governance/active-gates.md` | helper（`sync`） | 人类可读视图 |
| `.governance/programs/<p>/tree.md` | `init` | 程序树视图 |
| `.governance/programs/<p>/nodes.json` | 节点命令 | 节点真源（state-of-record） |
| `.governance/programs/<p>/cards/*.yaml` | `authorize` | 任务卡 |
| `.governance/steward/steward-index.json` | `steward-sync` | 跨工具责任索引 |
| `.governance/steward/current-next-gates.md` | `steward-sync` | 下一步 gate 视图 |
| `.governance/steward/evidence-index.md` | `steward-sync` | 证据索引 |
| `.governance/steward/tracks/*.md` | `steward-sync` | track 视图 |
| `.governance/file-to-track.json` | `map` | 文件→track 反向索引 |
| `.governance/drift-acceptances.json` | `accept-drift` | 漂移豁免审计日志 |
| `.governance/config.json` | `config set` | 治理配置 |
| `.governance/guards/pre-commit` | `install-guard` | git pre-commit |
| `.governance/guards/ft-scope-check.sh` | `install-guard` | PostToolUse scope-check |
| `.governance/backups/FUNCTION_TREE.*.md` | `doc` | 刷新前备份 |
| `FUNCTION_TREE.md`（仓库根） | `init`/`doc` | 业务项目功能树 |

## 6. Skill 自身文件契约

| 路径 | 角色 |
|---|---|
| `SKILL.md` | 触发器、命令表、Phase 1-4 规则、硬规则（权威文档，本文件为其镜像） |
| `scripts/ft-governance.cjs` | 单一入口，分发到 `lib/commands-*.cjs` |
| `scripts/lib/mainline.cjs` | 主线分层逻辑 |
| `scripts/lib/scan-{project,routes,pkg-manifest,ecosystem}.cjs` | 自动发现（候选源） |
| `scripts/lib/{nodes,programs,gates,doc,config,validate,steward,helpers,io-utils,constants}.cjs` | 核心域逻辑 |
| `references/STATE_MACHINE.md` | 状态、迁移、证据类、命令工作流 |
| `references/STEWARD_PROFILE.md` | 跨工具责任边界、节点字段、质量规则 |
| `templates/{node.json, task-card.yaml, program-tree.md}` | 确定性起始模板 |
| `guards/ft-scope-check.sh` | PostToolUse 钩子样本 |
| `tests/ft-governance.test.cjs` | 命令级回归测试（36.8K） |

## 7. 推荐使用流程

```
# 第一次进入新仓库
/ft:init                       # 自动推断 program = basename(root)
/ft:status                     # 看候选数量与覆盖提示

# 建立基线（按需选一）
/ft:suggest-nodes <program> --yes   # 全景录入（README + 代码 + 路由 + TODO）
/ft:promote-readme <program>        # 仅 README 主张 → mainline
/ft:promote-untracked <program>     # 把 git 工作区未跟踪文件 → backlog

# 看清主线
/ft:mainline                   # 验证唯一 active mainline + switch-lock
/ft:map                        # 重建 file→track 索引

# 开工前授权
/ft:authorize <program> <node-id> --allowed <paths> --non-goal <t> \
                --commit-gate @ci --closeout-gate <check>
# 写代码……（每次 Edit 触发 pre-edit；每次 commit 触发 drift-check --staged）

# 收尾
/ft:closeout <program> <node-id> --summary <path-or-note>
```

## 8. 硬规则（强制约束）

- 不允许从 `evidence-prepared` / `decision-prepared` / `authorization-prepared` 直接改源码
- 不允许跳过证据收集就授权
- 不允许用 GitHub issue/PR 作为状态机真源；只信 git commit/branch/diff
- 不手改生成的 active gate markdown；改 JSON → `sync`
- 不手改生成的 steward 工件；改 program nodes → `steward-sync`
- 不手改 `FUNCTION_TREE.md` 的生成区；持久笔记写 project-notes 区块后跑 `doc`
- 证据 `current_head` ≠ 当前 `HEAD` 时，必须先把节点标 stale 再走 implementation
- 项目特定的 impact/build/test/compliance gate 必须在授权前显式写入 `--commit-gate` / `--closeout-gate`

## 9. 与方法论的对齐（盲区 → 命令）

| 盲区 | 信号 | 命令 |
|---|---|---|
| A | pkg 根子包未挂节点 | `promote-pkgs` |
| B | README H2/H3 未挂主线 | `promote-readme` |
| C | manifest entry-points 未挂节点 | `promote-entrypoints` |
| D | git 工作区未跟踪文件（最强开工信号） | `promote-untracked` |
| E5 | CHANGELOG 发布要点 | `promote-changelog` |

## 10. 维护规约

- 改命令实现：`scripts/lib/commands-*.cjs` + `tests/ft-governance.test.cjs`
- 加命令：`SKILL.md` 命令表 + 本文件 §3 + `--help` 文本 + 测试
- 改状态机：`references/STATE_MACHINE.md` + `lib/validate.cjs` + 测试
- 改配置键：`lib/config.cjs` + 本文件 §3.6 + `SKILL.md` Phase 4 配置表
- 任何命令/文件契约变更：同步本文件 §3 / §5 / §6
