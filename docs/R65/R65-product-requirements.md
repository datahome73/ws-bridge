# R65 产品需求 — 管线状态同步 🎯

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-02
> **本轮改动范围：** `server/handler.py`（可能新增 `server/pipeline_sync.py`）
> **参考：** R64 管线执行教训（状态机滞后问题）、R63 time_tracker/watchdog 代码风格、TODO.md F-17

---

## 1. 问题背景

### 1.1 现状：状态机滞后，PM 反复人工诊断

当前管线状态机（`_PIPELINE_STATE`）的更新**只有唯一入口**：`!step_complete` / `!step_handoff` 命令调用。

但在实际运行中，各角色（arch/dev/review/qa）完成工作后**通过 git push 提交产出，但不一定会调用 `!step_complete`**。导致：

```
实际工作流（git push 视角）：
  Step 2 (arch) ──git push──→ Step 3 (dev) ──git push──→ Step 4 (review) ──git push──→

状态机视角（_PIPELINE_STATE）：
  Step 2 ⬜ 当前 → ... 静默等待 ... 时间流逝 → 仍在 Step 2
```

**R64 实测数据：**

| 维度 | 状态机显示 | 实际 git 进度 |
|:----|:---------:|:------------:|
| Step 2 | ⬜ 当前 | ✅ 已提交 |
| Step 3 | ⏳ 未来 | ✅ 已提交 |
| Step 4 | ⏳ 未来 | ✅ 已提交 |
| Step 5 | ⏳ 未来 | ⏳ 待处理 |

PM 必须执行以下手工流程才能修复：
```
① !pipeline_status → 看状态机在哪
② git log --oneline -5 origin/dev → 看实际进度
③ !step_complete step2 --output <sha>
④ !step_complete step3 --output <sha>
⑤ !step_handoff step4 --output <sha>
⑥ 人工 @bot_name 点名下一角色
```

**每轮都要重复这个诊断流程，严重违背「自动化」目标。**

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| ① | **状态机与产出脱钩** | `_PIPELINE_STATE` 增量仅通过 `!step_complete` 更新，与 git 产出无关联 |
| ② | **缺乏自动检测机制** | 没有 watchdog 检测「分支上是否出现了新 commit 对应当前 Step」 |
| ③ | **bot 不习惯调命令** | 各角色更习惯「推码=完成」，忘记了 `!step_complete` 的仪式步骤 |
| ④ | **ACK 超时误判** | ACK 30s 超时标记 ❌ FAILED，但 bot 实际正在工作中（R63 已发现） |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:----|:------|
| 🔴 **每轮必犯** | R62/R63/R64 三轮都出现状态机滞后问题 |
| 🔴 **PM 负担重** | 手工诊断+推进每次 ~5 分钟，且必须在多会话间核对 |
| 🟡 **自动化瓶颈** | 管线「全自动」的最后一块拼图——Step 间流转自动化 |
| 🟢 **改动可控** | 复用 R63 timeout_tracker/watchdog 模式，增加一个 git 同步检测模块 |
| 🟢 **退化安全** | 配置开关 + 旧 `!step_complete` 并行，零风险回退 |

---

## 2. 功能需求

### 设计原则

> **git 驱动流转，命令做补充：** 状态机优先通过 git 检测自动推进，`!step_complete` / `!step_handoff` 作为补充/手动覆盖手段，两者并行不冲突。
> **克制改动：** 不引入外部依赖（不需要 git webhook、不需要 CI 回调），纯 server 端定时检测。
> **退化优先：** `R65_ENABLE_GIT_SYNC` 配置开关，默认开启。

---

### 方向 A（核心）：git 驱动的管线自动同步 🔴 P0

#### 核心思路

在 pipeline 活跃期间，server 启动一个轻量 **git 同步 watchdog**，周期性（默认每 2 分钟）执行：

```
1. git fetch origin <pipeline_branch>             # 获取远程最新
2. git log --format="%H %an %s" <last_sha>..origin/<branch>  # 新 commits
3. 逐个检查：commit 是否有对应产出？
4. 如果确认有新产出 → 自动推进到下一 step
```

#### A1 — Git 同步检测模块（`server/pipeline_sync.py`，新增）

**位置：** 新增文件 `server/pipeline_sync.py`

```python
class PipelineGitSync:
    """
    管线 git 同步检测器。
    周期性检查 pipeline 工作分支的新提交，自动推进状态机。
    """

    def __init__(self, pipeline_id: str, config: dict):
        self._pipeline_id = pipeline_id
        self._branch = config.get('branch', 'dev')
        self._last_sha = config.get('last_output_sha', '')
        self._repo_path = config.get('repo_path', '/opt/data/ws-bridge')

    async def sync(self) -> dict:
        """
        检查 git 是否有新提交，如有则推进状态机。
        返回: {synced: bool, from_step: int, to_step: int, new_sha: str}
        """

    def _get_new_commits(self) -> list:
        """git fetch + git log 获取新提交"""

    def _match_commit_to_step(self, commit: dict) -> int | None:
        """
        将 commit 匹配到 Step。
        匹配规则（任一满足即可，按优先级匹配）:
        1. commit message 含 Step 标记（feat/fix/docs(R{N}):）
        2. commit 修改了 Step 指定的产出文件
        3. commit author 是当前 Step 的角色
        4. 兜底: 活跃 pipeline 期间的任意新 commit
        """
```

**兜底规则解释：** 在 pipeline 活跃期间，dev 分支的新 commits 都应该是本轮产出。如果 bot 推了码但没有 `!step_complete`，至少有新 SHA 可以证明「Step 有工作」。兜底后自动推进，万一流转到错误的角色 → 角色发现不对会退回。

#### A2 — Watchdog 集成（handler.py 修改）

**位置：** `server/handler.py` — 新增 `_pipeline_git_sync_scan`，与 R63 timeout_tracker 的 watchdog 并行运行。

```python
async def _pipeline_git_sync_scan(self):
    """定时扫描所有活跃管线，检查 git 同步。"""
    for pid, pstate in list(self._PIPELINE_STATE.items()):
        if pstate.get('status') not in ('active', 'running'):
            continue
        if not config.R65_ENABLE_GIT_SYNC:
            continue

        sync = PipelineGitSync(pid, self._PIPELINE_CONFIG.get(pid, {}))
        result = await sync.sync()

        if result and result['synced']:
            await self._auto_advance_pipeline(pid, result)
```

**集成点：**

| 集成 | 说明 |
|:-----|:------|
| 启动时机 | 管线启动后自动激活 git_sync，管线关闭/归档后停止 |
| 检测间隔 | 默认 120 秒（可配置 `git_sync_interval`） |
| 与 ACK 关系 | 若 ACK 已超时标记 FAILED，但 git sync 发现新 commit → **覆盖 FAILED 标记，推进状态机** |
| 与 timeout 关系 | timeout_tracker 的超时仍然有效——如果超时 + 无新 git commit，才是真正死锁 |
| 并行限制 | 同一时刻只执行一次 git fetch（防并发冲突） |

#### A3 — 同步动作：自动推进状态机

当 git sync 检测到需要推进时：

```
1. 更新 _PIPELINE_STATE[current_step] → status: 'completed'
2. 更新 _PIPELINE_STATE[next_step] → status: 'current'
3. 记录 last_output_sha → 新 commit SHA
4. 广播到工作室：💻 R65 Step N 已自动同步（git commit: <sha>）
5. 点名下一角色（复用 R63 @role_name → @bot_name 机制）
6. 启动 next step 的 timeout_tracker 倒计时
```

**与 `!step_complete` 的关系：**

| 场景 | `!step_complete` | Git 自动同步 | 结果 |
|:-----|:---------------:|:------------:|:-----|
| bot 调用了命令 | ✅ 正常推进 | 跳过（已是最新） | 正常 |
| bot 推码没调命令 | ⏳ 未调用 | ✅ 自动检测推进 | 管线继续 |
| 有人调了命令但没推码 | ✅ 正常推进 | 不检测（同 SHA） | 正常 |
| 两者同时触发 | ✅ 命令优先，git sync skip | — | 安全 |

#### A4 — `!pipeline_status` 增强

**当前：** 显示当前 Step 和倒计时。
**改造后：** 在 status 输出中增加 git 同步信息行：

```
📊 R65 管线状态
━━━━━━━━━━━━━━━━━
| Step | 角色 | 状态 | 产出 SHA |
|:----:|:----:|:----:|:--------:|
| 1 | PM | ✅ 已完成 | d5d9e12 |
| 2 | Arch | ✅ 已完成 | 573adb9 |
| 3 | Dev | ✅ 已完成 | 7aeb824 |
| 4 | Review | ◀ 当前 | — |
🔄 Git 同步: 启用 ✅（上次检查: 30s 前, dev 分支）
```

#### A5 — 配置项

| 配置 | 默认值 | 说明 |
|:-----|:------:|:------|
| `R65_ENABLE_GIT_SYNC` | `true` | 主开关 |
| `git_sync_interval` | `120` (秒) | 检测间隔 |
| `git_sync_branch` | `dev` | 默认工作分支 |
| `git_sync_fallback` | `true` | 兜底规则（新 commit 即推进）启用 |

---

### 方向 B（辅助）：`!step_complete` 降摩擦 🟡 P2

**问题：** 当前 `!step_complete` 需要带 `--output <sha>` 参数，bot 经常忘。

**改造：** 允许 `!step_complete` 无参数时自动检测最新 commit SHA：

```python
async def _cmd_step_complete(self, ...):
    output = m.group('output_ref') or self._auto_detect_latest_sha()
    # _auto_detect_latest_sha(): git log -1 --format=%H
```

当 `--output` 缺失时：
1. 自动取 `git log -1 --format=%H origin/<branch>` 的最新 SHA
2. 记录为 output_sha
3. 正常推进状态机

---

### 方向 C（辅助）：ACK 超时标记优化 🟢 P3

**问题：** R63 ACK 状态机的 30s 超时标记 ❌ FAILED，但 bot 可能正在工作中。FAILED 标记导致 PM 误判。

**改造：** 当 ACK 超时时，不做 ❌ FAILED，改为 `⚠️ ACK 超时（继续等待 git 产出）`。只有当 git sync 和 timeout_tracker 都确认无产出时才标记真正 FAILED。

---

## 3. 验收标准

### 🎯 3.1 方向 A（git 自动同步）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 管线启动后 git_sync watchdog 自动启动 | handler 日志显示 `[GitSync] R65 watchdog started` | 日志检查 |
| ✅-2 | 当前 Step 有新 commit 推 dev 分支 → 自动推进 | 状态机推进到下一 Step（不需要 `!step_complete`） | 实测：推一个 commit，等 ~2 分钟后查 `!pipeline_status` |
| ✅-3 | 多 Step 连续推码 → 自动逐个推进 | 从 Step 2 一路推进到 Step 6 | 实测：连续推 commit 到 dev |
| ✅-4 | git sync 推进后，下一角色被自动点名 | 工作室出现 `@bot_name 🏗️ Step N 到你了！` | 实测 |
| ✅-5 | ACK 超时 FAILED + 有新 git commit → 覆盖 FAILED，正常推进 | FAILED 标记被清除，状态机推进 | 模拟：触发 ACK 超时，再 git push |
| ✅-6 | 无新 commit 时不推进状态机 | 状态不变 | 实测 |
| ✅-7 | `R65_ENABLE_GIT_SYNC = false` → watchdog 不启动 | 零行为变化，恢复为手动模式 | 配置开关测试 |
| ✅-8 | 与 `!step_complete` 并行无冲突 | 两者都能正确推进，不重复推进 | 实测：调 `!step_complete` 的同时 git push |
| ✅-9 | `!pipeline_status` 显示 git sync 状态行 | 能看到「🔄 Git 同步: 启用/关闭」 | 实测 |
| ✅-10 | git fetch 失败（网络问题）→ 静默跳过，不报错 | 日志 warning，下次重试 | 模拟网络断连 |
| ✅-11 | 管线关闭后 git sync 停止 | 不再有 `[GitSync]` 日志输出 | 实测 |
| ✅-12 | 兜底规则：pipeline 活跃期间任意新 commit → 推进 | dev 分支有新 commit（不匹配产出文件）→ 仍然推进 | 实测 |
| ✅-13 | 匹配规则精度：文件匹配 > author 匹配 > 兜底 | 各优先级正确触发 | 单元测试 |

### 🎯 3.2 方向 B（降低 `!step_complete` 摩擦）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-14 | `!step_complete step3` 无 `--output` → 自动取最新 SHA | 正常推进，output = `git log -1` 结果 |
| ✅-15 | `!step_complete step3 --output abc123` → 使用指定值 | 行为不变 |

### 🎯 3.3 方向 C（ACK 超时优化）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-16 | ACK 超时 → 显示 `⚠️ ACK 超时（等待 git 产出）`，不标 ❌ | 状态机不被 FAILED 阻塞 |
| ✅-17 | ACK 超时 + 无 git 产出 + timeout 超时 → 真正 FAILED | 此时才标记真正失败 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| Webhook / GitHub Webhook 集成 | 外部回调触发管线推进 | 增加外部依赖，本轮纯 server 端解决 |
| 自动识别「谁该接收下一棒」 | 仍用现有角色映射 + @mention | Agent Card 映射 R63 已建好，直接复用 |
| 跨管线 git 检测 | 多管线并行时的 git 分支冲突 | 当前单管线够用 |
| CI/CD 集成 | 不触发 Docker 构建 | 超出本轮范围 |
| `!step_reject` / 退回机制 | 不改造退回流程 | 当前够用 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 20min |
| **3** | 👨‍💻 Dev | 编码（新建 + 修改） | 25min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/pipeline_sync.py` | **新增** — Git 同步检测模块 | ~180 行 |
| `server/handler.py` | **修改** — 集成 watchdog + `!step_complete` 增强 + status 增强 | ~30 行 |
| `server/config.py` | **修改** — 新增 R65 配置项 | ~10 行 |
| docs/R65/* | **新增** — 文档 | ~100 行 |
| **合计** | | **~220 行净增，~30 行修改** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `git fetch` 在网络差时阻塞 | watchdog 卡住 | 超时 10s，失败静默跳过 |
| 多人同时推码 → 多个 commit 批量推进一 Step | 状态机跳太快跳过中间步骤 | 按 commit 时间逐个匹配检测 |
| git 凭证在容器内不可用 | 检测始终失败 | 降级为纯手动模式（退化开关自动 fallback） |
| 兜底规则太宽松 → 错误推进 | 角色收到不属自己的工作 | 推进后下一角色会检查 scope（拒绝机制） |

---

## 6. 脱敏检查清单

- [ ] docs/R65/*.md 零内部名残留
- [ ] `grep -n '内部名模式' docs/R65/*.md` 零匹配
- [ ] server/pipeline_sync.py 零内部 URL/端口泄露
- [ ] handler.py diff 零内部信息泄露
