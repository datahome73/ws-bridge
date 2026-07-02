# R65 工作计划 — 管线状态同步

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R65/R65-product-requirements.md v1.0 ✅（项目负责人审核通过）

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小，严禁 scope creep**

| 不改入 | 说明 |
|:-------|:------|
| `server/agent_card.py` | Agent Card schema R63 已定，不涉及 |
| `server/timeout_tracker.py` | 倒计时模块不动，只复用其格式/API |
| `gateway-plugin/` | Gateway 层不改 |
| Web UI / 前端 | 纯服务端改动 |
| 新外部依赖 | 纯 stdlib + git CLI |

| 不改出 | 说明 |
|:-------|:------|
| 不引入 git webhook | 纯服务端定时检测 |
| 不做 CI/CD 集成 | 超出本轮 |
| 不改造 `!step_reject` | 退回机制不动 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py` + 新增 `server/pipeline_sync.py` + `server/config.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | **新增** `server/pipeline_sync.py` — `PipelineGitSync` 类核心 | 新文件 | ~180 行 |
| 2 | A2 | **修改** `handler.py` — watchdog 添加 `_pipeline_git_sync_scan()` 调用 | L1213 附近 | ~20 行 |
| 3 | A3 | **修改** `handler.py` — 新建 `_auto_advance_pipeline()` 自动推进函数 | 同文件新函数 | ~40 行 |
| 4 | A4 | **修改** `handler.py` — `_cmd_pipeline_status` 增加 git sync 状态行 | L2828 附近 | ~8 行 |
| 5 | B1 | **修改** `handler.py` — `_cmd_step_complete` 允许无 `--output` | L1932 附近 | ~5 行 |
| 6 | C1 | **修改** `handler.py` — ACK 超时不标 FAILED 改为等待标记 | L2200 附近 | ~8 行 |
| 7 | A5 | **修改** `config.py` — 新增 R65 配置项 | L117 后 | ~6 行 |

**总估算：** ~267 行净增，~47 行修改

### 与 R63/R64 基础设施的交互

```
                              ┌──────────────────────┐
                              │   _PIPELINE_STATE     │
                              │   _PIPELINE_CONFIG    │
                              └──────┬───────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
   ┌────▼────┐                ┌──────▼──────┐           ┌────────▼────────┐
   │R63      │                │R65          │           │R63              │
   │timeout  │                │PipelineGit  │           │ACK 状态机       │
   │tracker  │                │Sync         │           │(R64 已增强)     │
   └─────────┘                └──────┬──────┘           └────────┬────────┘
                                     │                            │
                                     │  自动推进                  │  覆盖 ACK
                                     │  状态机                    │  FAILED 标记
                                     └────────────┬───────────────┘
                                                  │
                                          ┌───────▼────────┐
                                          │ @角色名 点名     │
                                          │ 下一 Step       │
                                          └────────────────┘
```

---

## 2. 管线步骤

### Step 1: PM 准备 + 管线启动（此文档）

**主角：** PM（需求分析师）
**备用：** —
**产出：** 此 WORK_PLAN + 管线启动命令

**完成条件：**
- WORK_PLAN 推 dev 分支
- `!pipeline_start R65 --work_plan_url <raw_url>`
- 工作室创建 + 点名全员到位

---

### Step 2: 技术方案（Arch）

**主角：** arch（架构师）
**备用：** dev（开发工程师）
**产出：** `docs/R65/R65-tech-plan.md` 推 dev 分支
**预计耗时：** 20 分钟

**任务描述：**

产出技术方案文档，涵盖：

#### A1 — `server/pipeline_sync.py` 全模块设计

```python
PipelineGitSync.__init__(pipeline_id, config)
  - 从 _PIPELINE_CONFIG 读取 branch / repo_path / last_sha
  - 存储 _step_config: Dict[str, StepConfig]

PipelineGitSync.sync() -> dict | None
  - git fetch origin <branch>  (超时 10s)
  - git log <last_sha>..origin/<branch>  (new commits)
  - 逐个 commit 匹配当前 step（4 级优先级）
  - 有匹配 → 返回 {synced, from_step, to_step, new_sha, commit}
  - 无匹配 → 返回 None

PipelineGitSync._get_new_commits() -> list[dict]
  - 执行 git log 获取 {sha, author, message, files}
  - 失败时返回空列表，不抛异常

PipelineGitSync._match_commit_to_step(commit, current_step_idx) -> bool
  优先级:
    1. commit message 含 Step 标记（feat(R{N}): mode等）
    2. commit 修改了 Step 配的产出文件
    3. commit author 匹配当前 Step 角色
    4. 兜底: pipeline 活跃期间任意新 commit
```

**匹配精度要求：** 用函数指针/策略模式让各匹配规则可组合，方便后续调整。默认启用兜底规则但可在配置中关闭。

**git fetch 安全：**
- 超时 10s，网络失败静默跳过（仅 warning 日志）
- 同一时刻只执行一次 fetch（互斥锁）
- 使用 `cwd=repo_path` 执行，不改变进程 cwd

#### A2 — handler.py watchdog 集成方案

```python
async def _watchdog_scan():
    # 现有 R43 watchdog 逻辑保持不变
    ...

    # 新增: R65 git sync scan
    if config.ENABLE_GIT_SYNC:
        await _pipeline_git_sync_scan()
```

`_pipeline_git_sync_scan()` 遍历 `_PIPELINE_STATE`，对每个活跃管线创建 `PipelineGitSync` 实例并调用 `sync()`。有结果则调 `_auto_advance_pipeline()`。

**启动时机：** 在 `_ensure_watchdog()` 中一并启动——复用现有 10 分钟间隔还是使用独立短间隔（如 120 秒）？建议独立间隔，因为 git sync 需要更频繁的检测（2 分钟），而 R43 watchdog 的 10 分钟间隔用于超时告警。

**方案对比：**

| 方案 | 描述 | 复杂度 |
|:----|:-----|:------:|
| **方案 A**（推荐） | watchdog_scan 内新增 `_pipeline_git_sync_scan()` 独立扫描，与 R43 逻辑解耦 | 低 |
| **方案 B** | 在 `_pipeline_git_sync_scan` 中自托管 loop（asyncio.create_task），不依赖 watchdog | 中 |
| **方案 C** | 模块化：`pipeline_sync.py` 自带启动/停止接口，handler 只负责调 start/stop | 中 |

#### A3 — `_auto_advance_pipeline()` 设计

```python
async def _auto_advance_pipeline(round_name: str, result: dict) -> None:
    """Git sync 检测到新产出后自动推进状态机。"""
    pstate = _PIPELINE_STATE[round_name]
    step_config = _load_step_config()
    current_step = pstate.get("current_step")
    next_step = _get_next_step(current_step, step_config)

    if not next_step:
        return  # 已是最后一步

    # 1. 推进状态机
    pstate["current_step"] = next_step
    pstate[current_step]["status"] = "completed"
    pstate["last_output_sha"] = result["new_sha"]

    # 2. 清理旧 ACK/FAILED 标记
    ...  # 复用 R63 ACK cleanup

    # 3. 广播自动同步消息
    await _broadcast_to_workspace(
        pstate["ws_id"],
        f"💻 {round_name} {current_step} 已自动同步（commit: {result['new_sha'][:7]}）\
        \n→ 交棒 {next_step}"
    )

    # 4. 点名下一角色（复用 R63 @role_name → @bot_name 方式）
    next_role = step_config[next_step]["role"]
    agent_ids = _get_agents_by_role(next_role)
    for aid in agent_ids:
        agent_name = _ROLE_AGENT_MAP.get(aid, {}).get("name", aid)
        await _send_to_agent(
            aid, f"@{agent_name} 🏗️ {round_name} {next_step} 到你了！"
        )

    # 5. 启动下一 Step timeout_tracker（R63 倒计时）
    if config.R63_ENABLE_TIMEOUT:
        timeout_min = step_config[next_step].get("timeout_minutes", 20)
        timeout_tracker.start_timer(round_name, next_step, timeout_min)
```

**注意：** 复用的 R63 函数（`_get_agents_by_role`、`_send_to_agent`、`timeout_tracker`、`_ROLE_AGENT_MAP`）都已存在——不需要改动它们。

#### A4 — `!pipeline_status` git sync 行

在状态输出的已停止区块（After step list, before `if not lines` check），添加：

```python
# ── R65 A4: Git sync status line ──
if config.ENABLE_GIT_SYNC and round_name in _PIPELINE_STATE:
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    branch = pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH)
    last_sync_ts = pstate.get("_last_git_sync_ts", 0)
    last_sync_display = f"{int(time.time() - last_sync_ts)}s 前" if last_sync_ts else "—"
    lines.append(f"  🔄 Git 同步: 启用 ✅（{branch}，{last_sync_display}）")
```

#### A5 — config.py 新增配置

```python
# ── R65: Git pipeline sync ──────────────────────────────────
ENABLE_GIT_SYNC: bool = os.environ.get("R65_ENABLE_GIT_SYNC", "1") == "1"
GIT_SYNC_INTERVAL: int = int(os.environ.get("R65_GIT_SYNC_INTERVAL", "120"))
GIT_SYNC_BRANCH: str = os.environ.get("R65_GIT_SYNC_BRANCH", "dev")
GIT_SYNC_FALLBACK: bool = os.environ.get("R65_GIT_SYNC_FALLBACK", "1") == "1"
```

#### B1 — `_cmd_step_complete` 无 `--output`

```python
# 在 _cmd_step_complete 中
output_ref = params.get("output", "")

# ── R65 B1: Auto-detect SHA when --output is missing ──
if not output_ref:
    branch = GIT_SYNC_BRANCH
    try:
        output_ref = await _auto_detect_latest_sha(repo_path, branch)
    except Exception:
        return "❌ 缺少 --output <sha>，且无法自动检测最新 commit"
```

`_auto_detect_latest_sha()`: 简单的 `subprocess.run(["git", "log", "-1", "--format=%H", f"origin/{branch}"], cwd=repo_path, capture_output=True, timeout=5)`

#### C1 — ACK 超时不标 FAILED

```python
# 在 _ack_timeout_task() 或 _update_step_ack_state() 中
if expired and not acked:
    # 当前: step 标记 FAILED
    # 改造后:
    step_ack_state["status"] = "ack_timeout"  # 而非 "failed"
    logger.info(
        "[R65 C1] ACK 超时（step=%s）— 等待 git 产出，不标 FAILED",
        step_key,
    )
```

真正 FAILED 的判断条件：ACK 超时 && 无新 git commit && timeout_tracker 超时。

---

### Step 3: 编码（Dev）

**主角：** dev（开发工程师）
**备用：** arch（架构师）
**产出：** 4 个文件的改动推 dev 分支
**预计耗时：** 25 分钟
**约束：** 写方案的人 ≠ 编码的人 ✅

**实现要点：**

#### 1. `server/pipeline_sync.py`（新建）

- 参考 `server/timeout_tracker.py` 的独立模块风格（无 async 构造、纯内存、轻量日志）
- git CLI 调用用 `asyncio.create_subprocess_exec`（非阻塞）
- 核心方法 `sync()` 是 async，返回 dict 或 None
- `__init__` 是同步的，只需存储配置
- `_get_new_commits()` 内部用 `git fetch --no-tags origin <branch>`（更快）
- 使用 `asyncio.Lock` 保证同一管线同一时间只有一个 fetch

#### 2. `server/handler.py` 修改

**精确改动点：**

| 改动 | 位置（基于 origin/dev 基线） | 内容 |
|:-----|:----------------------------|:-----|
| 导入 | 文件头部（~L40） | `from server import pipeline_sync` |
| watchdog 集成 | `_watchdog_scan()` 函数内（~L1234） | 末尾加 `await _pipeline_git_sync_scan()` |
| 新建 `_pipeline_git_sync_scan()` | 在 `_watchdog_scan` 附近 | 遍历 `_PIPELINE_STATE`，对活跃管线调 `sync()` |
| 新建 `_auto_advance_pipeline()` | 同区域 | 推进状态机 + 广播 + 点名 + 起倒计时 |
| status 增强 | `_cmd_pipeline_status`（~L2900） | 加 git sync 状态行 |
| `_cmd_step_complete` 修改 | L1932 附近 | 无 `--output` 时自动取最新 SHA |
| ACK 超时优化 | `_ack_timeout_task` 附近（~L2200） | 超时不标 FAILED |

#### 3. `server/config.py` 修改

在 R63 配置块后追加 R65 配置项（5 行）。

---

### Step 4: 审查（Review）

**主角：** review（审查工程师）
**备用：** qa（测试工程师）
**预计耗时：** 15 分钟

**审查重点：**
1. ✅ scope 合规——仅改动 handler.py + 新建 pipeline_sync.py + config.py
2. ✅ `pipeline_sync.py` 的 git 调用是否安全（超时、错误处理、输入消毒）
3. ✅ `_auto_advance_pipeline()` 与现有 `_cmd_step_complete` / `_cmd_step_handoff` 是否冲突
4. ✅ 配置开关 `R65_ENABLE_GIT_SYNC=false` 时是否零行为变化
5. ✅ ACK 超时改动的完整性（不做半截 FAILED 标记）
6. ✅ `grep -n '内部名'` 零残留

---

### Step 5: 测试（QA）

**主角：** qa（测试工程师）
**备用：** review（审查工程师）
**预计耗时：** 15 分钟

**测试矩阵（对应 17 项验收标准）：**

| # | 验收项 | 测试方法 | 方法级别 |
|:-:|:-------|:---------|:--------:|
| ✅-1 | watchdog 自动启动 | 日志 `[GitSync]` 检查 | 代码审计 |
| ✅-2 | 新 commit → 自动推进 | 模拟 git push 到 origin/dev | 模拟验证 |
| ✅-3 | 连续多 commit → 逐 Step 推进 | 模拟 3 个 commit | 模拟验证 |
| ✅-4 | 推进后自动点名 | 监听 `_send_to_agent` | 代码审计 |
| ✅-5 | ACK FAILED + git commit → 覆盖推进 | 触发 ACK 超时 + git push | 模拟验证 |
| ✅-6 | 无新 commit → 不推进 | 同 SHA → 状态不变 | 模拟验证 |
| ✅-7 | 配置开关关闭 → 纯手动模式 | `R65_ENABLE_GIT_SYNC=false` | 环境实测 |
| ✅-8 | 与 `!step_complete` 并行无冲突 | 同时调命令和 git push | 模拟验证 |
| ✅-9 | status 显示 git sync 行 | `!pipeline_status` 输出检查 | 环境实测 |
| ✅-10 | git fetch 失败 → 静默跳过 | 模拟网络断连 | 模拟验证 |
| ✅-11 | 管线关闭后停止 | 关闭后检查日志 | 环境实测 |
| ✅-12 | 兜底规则：任意新 commit → 推进 | 推非产出文件 commit | 模拟验证 |
| ✅-13 | 匹配精度正确 | 各优先级 mock 测试 | 代码审计 |
| ✅-14 | `!step_complete` 无 `--output` | 不传参调命令 | 环境实测 |
| ✅-15 | `!step_complete` 有 `--output` | 传参调命令 | 环境实测 |
| ✅-16 | ACK 超时不标 ❌ | 触发 ACK 超时 | 模拟验证 |
| ✅-17 | ACK + git + timeout 全超时 → 真正 FAILED | 三条件全触发 | 模拟验证 |

---

### Step 6: 合并部署归档（Admin）

**主角：** admin（项目管理）
**备用：** arch（架构师）
**预计耗时：** 10 分钟

**操作：**
1. 合并 dev→main
2. `docker build -t ws-bridge:r65 .`
3. `docker compose up -d` 部署生产
4. 配置开启 `R65_ENABLE_GIT_SYNC=true`
5. 验证管线自动推进（推一个 commit 到 dev，等 2 分钟看是否自动流转）
6. `!close_workspace` 关闭 R65 工作室
7. `TODO.md` 更新：F-17 标记 ✅

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | 管线启动后 git_sync watchdog 自动启动 | ⏳ |
| ✅-2 | 当前 Step 有新 commit → 自动推进 | ⏳ |
| ✅-3 | 多 Step 连续推码 → 自动逐个推进 | ⏳ |
| ✅-4 | git sync 推进后下一角色被自动点名 | ⏳ |
| ✅-5 | ACK 超时 + 有新 git commit → 覆盖 FAILED | ⏳ |
| ✅-6 | 无新 commit 时不推进状态机 | ⏳ |
| ✅-7 | `R65_ENABLE_GIT_SYNC = false` → 手动模式 | ⏳ |
| ✅-8 | 与 `!step_complete` 并行无冲突 | ⏳ |
| ✅-9 | `!pipeline_status` 显示 git sync 状态行 | ⏳ |
| ✅-10 | git fetch 失败（网络问题）→ 静默跳过 | ⏳ |
| ✅-11 | 管线关闭后 git sync 停止 | ⏳ |
| ✅-12 | 兜底规则：任意新 commit → 推进 | ⏳ |
| ✅-13 | 匹配规则精度正确 | ⏳ |
| ✅-14 | `!step_complete` 无 `--output` → 自动取 SHA | ⏳ |
| ✅-15 | `!step_complete` 有 `--output` → 正常行为 | ⏳ |
| ✅-16 | ACK 超时不标 ❌ FAILED | ⏳ |
| ✅-17 | ACK + git + timeout 全超时 → 真正 FAILED | ⏳ |

---

## 4. 脱敏检查清单

- [ ] docs/R65/*.md 零内部名残留
- [ ] `grep -n '内部名模式' docs/R65/*.md` 零匹配
- [ ] `server/pipeline_sync.py` 零内部 URL/端口泄露
- [ ] handler.py / config.py diff 零内部信息

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-02 | 初稿，基于 R65 需求文档 v1.0 ✅ |
