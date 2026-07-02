# R65 技术方案 — 管线状态同步 🏗️

> **版本：** v1.0
> **状态：** ✅ 已审核
> **架构师：** 🏗️ arch
> **基于：** docs/R65/R65-product-requirements.md v1.0 ✅、docs/R65/WORK_PLAN.md v1.0 ✅
> **日期：** 2026-07-02

---

## 1. 总体设计

### 1.1 改动文件清单

| # | 文件 | 改动类型 | 估算行数 |
|:-:|:-----|:---------|:--------:|
| 1 | `server/pipeline_sync.py` | **新增** | ~180 行 |
| 2 | `server/handler.py` | **修改**（4 处） | ~73 行 |
| 3 | `server/config.py` | **修改**（追加） | ~6 行 |
| | **合计** | | **~259 行** |

### 1.2 架构图

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
     │                            │                            │
     │  超时告警                  │  自动推进                  │  覆盖 ACK
     │  (仅告警)                  │  状态机                    │  FAILED 标记
     └────────────┬───────────────┴────────────┬───────────────┘
                  │                            │
          ┌───────▼────────┐          ┌────────▼────────┐
          │ @bot_name 点名  │          │  _auto_advance  │
          │ 下一 Step      │          │  _pipeline()    │
          └───────────────┘          └─────────────────┘
```

### 1.3 数据流

```
[git push to origin/dev]
        │
        ▼
[watchdog 每 120s 触发]
        │
        ▼
[_pipeline_git_sync_scan()]
    │ 遍历 _PIPELINE_STATE 活跃管线
    │ 为每条创建 PipelineGitSync 实例
    ▼
[PipelineGitSync.sync()]
    │ 1. git fetch origin <branch> (超时 10s)
    │ 2. git log <last_sha>..origin/<branch>
    │ 3. _match_commit_to_step() 匹配当前 Step
    │ 4. 有匹配 → 返回结果；无匹配 → None
    ▼
[_auto_advance_pipeline()]
    │ 1. 更新状态机 (current_step → next)
    │ 2. 清理 ACK FAILED 标记
    │ 3. 广播自动同步消息
    │ 4. 点名下一角色
    │ 5. 启动下一 Step timeout_tracker
    ▼
[管线推进完成]
```

---

## 2. 模块设计

### 2.1 A1 — `server/pipeline_sync.py`（新增）

#### 2.1.1 类接口

```python
class PipelineGitSync:
    """管线 git 同步检测器。周期性检查 pipeline 工作分支的新提交，自动推进状态机。"""

    def __init__(self, pipeline_id: str, config: dict):
        """
        Args:
            pipeline_id: 管线标识（如 "R65"）
            config: 配置字典，包含以下键：
                - branch: str (默认 "dev")
                - repo_path: str (默认 "/opt/data/ws-bridge")
                - last_sha: str (上次处理的 commit SHA, 空字符串表示首次)
                - fallback_enabled: bool (默认 True, 兜底规则开关)
        """
        ...

    async def sync(self) -> dict | None:
        """检查 git 是否有新提交，如有则推进状态机。

        Returns:
            {
                "synced": True,
                "from_step": "step2",
                "to_step": "step3",
                "new_sha": "abc123def456",
                "commit": {"sha": "...", "message": "...", "author": "..."}
            }
            or None if no new commits match.
        """
        ...

    def _get_new_commits(self) -> list[dict]:
        """git fetch + git log 获取新提交。

        Returns:
            [{"sha": str, "author": str, "message": str}, ...]
            失败时返回空列表（静默跳过，仅 warning 日志）。
        """
        ...

    def _match_commit_to_step(self, commit: dict, current_step_idx: int) -> bool:
        """将 commit 匹配到 Step。

        匹配优先级（返回最早匹配的规则）:
        1. commit message 含 Step 标记（feat(R{N}): / fix(R{N}): / docs(R{N}):）
        2. commit 修改了 Step 配置的产出文件（由 _PIPELINE_CONFIG.steps[].output_files 定义）
        3. commit author 匹配当前 Step 的角色名
        4. 兜底: pipeline 活跃期间任意新 commit（受 fallback_enabled 控制）
        """
        ...
```

#### 2.1.2 git CLI 调用安全

| 安全措施 | 实现 |
|:---------|:-----|
| 超时 | `asyncio.wait_for(fetch_coro, timeout=10.0)` |
| 并发锁 | `asyncio.Lock` — 同一管线同时只一个 fetch |
| 工作目录 | 通过 `cwd=repo_path` 参数传递，不改变进程 cwd |
| 失败处理 | 网络错误 / 超时 → 空列表 + `logger.warning`，不抛异常 |
| 凭证 | 复用现有 git remote 配置（origin-https），不硬编码 |
| fetch 优化 | `git fetch --no-tags origin <branch>` 减少传输量 |

#### 2.1.3 匹配规则实现细节

```python
# 规则1: commit message 含 Step 标记
STEP_MESSAGE_PATTERNS = [
    r'(?:feat|fix|docs|chore)\(R\d+\):',   # 标准 conventional commit
    r'R\d+\s+(?:Step|step)\s+\d+',         # 显式 Step 标记
    r'#\s*R\d+',                            # 引用标记
]

# 规则2: 产出文件匹配
# 从 _PIPELINE_CONFIG.steps[step_key].get("output_files", []) 获取
# 检查 commit 修改的文件列表中是否有匹配项

# 规则3: author 匹配
# 从 _ROLE_AGENT_MAP 获取当前 Step 角色的 agent_id 列表
# 检查 commit.author 是否匹配任一 agent 的 git config user.name

# 规则4: 兜底
# 只要 pipeline 活跃期间有新 commit 且当前 Step 有角色 active
# 推进状态机（按规则4推进时日志标记为 "fallback"）
```

#### 2.1.4 状态管理

```python
# 模块级变量
_pipeline_git_locks: dict[str, asyncio.Lock] = {}   # pipeline_id → Lock
_pipeline_git_tasks: dict[str, asyncio.Task] = {}    # pipeline_id → Task (for lifecycle)
```

---

### 2.2 A2 — Watchdog 集成（handler.py 修改）

#### 2.2.1 方案对比

| 方案 | 描述 | 复杂度 | 资源开销 | 推荐度 |
|:----|:-----|:------:|:--------:|:------:|
| **方案 A ✅** | `_watchdog_scan()` 尾部新增 `_pipeline_git_sync_scan()` | 低 | 低（每 120s 一次） | ⭐ 推荐 |
| 方案 B | `_pipeline_git_sync_scan` 自托管 loop（`asyncio.create_task`） | 中 | 中（独立协程） | |
| 方案 C | 模块化：`pipeline_sync.py` 自带 start/stop 生命周期 | 中 | 中 | |

**推荐方案 A** 的理由：
- `_watchdog_scan()` 每 10 分钟执行一次，而 git sync 需要更短间隔（120s）
- 方案 A 需要**独立定时器**而非绑定 watchdog 的 10 分钟间隔
- 实现：在 handler 中新增独立的 `_git_sync_task` 协程，而不是在 `_watchdog_scan` 内部

#### 2.2.2 推荐实现（方案 A 变体 — 独立定时器）

```python
# 新增模块级变量
_GIT_SYNC_TASK: asyncio.Task | None = None

async def _start_git_sync_loop():
    """独立的 git 同步定时循环，每 GIT_SYNC_INTERVAL 秒执行一次。"""
    while True:
        await asyncio.sleep(config.GIT_SYNC_INTERVAL)  # 默认 120s
        try:
            await _pipeline_git_sync_scan()
        except Exception as e:
            logger.warning("[R65] git_sync_scan error: %s", e)

def _ensure_git_scan():
    """在 handler 初始化时调用一次。"""
    global _GIT_SYNC_TASK
    if not config.ENABLE_GIT_SYNC:
        logger.info("[R65] Git sync 已禁用（ENABLE_GIT_SYNC=false）")
        return
    if _GIT_SYNC_TASK is None or _GIT_SYNC_TASK.done():
        _GIT_SYNC_TASK = asyncio.create_task(_start_git_sync_loop())
        logger.info("[R65] Git sync watchdog 已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)
```

#### 2.2.3 `_pipeline_git_sync_scan()` 实现

```python
async def _pipeline_git_sync_scan():
    """遍历所有活跃管线，检查 git 同步。"""
    for pid, pstate in list(_PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        if not config.ENABLE_GIT_SYNC:
            continue

        # 从 _PIPELINE_CONFIG 读取管线专属配置
        pconfig = _PIPELINE_CONFIG.get(pid, {})
        sync_config = {
            "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
            "repo_path": pconfig.get("repo_path", config.REPO_PATH),
            "last_sha": pstate.get("last_output_sha", ""),
            "fallback_enabled": config.GIT_SYNC_FALLBACK,
        }

        syncer = PipelineGitSync(pid, sync_config)
        result = await syncer.sync()

        if result and result.get("synced"):
            await _auto_advance_pipeline(pid, result)
            pstate["_last_git_sync_ts"] = time.time()
```

#### 2.2.4 启动时机

| 事件 | 行为 |
|:-----|:------|
| 管线启动（`!pipeline_start`） | `_ensure_git_scan()` — 首次启动 git sync loop |
| 管线关闭/归档 | 循环中存在性检查（不活跃管线自动跳过） |
| Server 重启 | handler 初始化时调用 `_ensure_git_scan()` |

---

### 2.3 A3 — `_auto_advance_pipeline()`（handler.py 新增函数）

```python
async def _auto_advance_pipeline(round_name: str, result: dict) -> str:
    """Git sync 检测到新产出后自动推进状态机。

    Args:
        round_name: 管线标识
        result: PipelineGitSync.sync() 返回值

    Returns:
        广播消息文本。
    """
    pstate = _PIPELINE_STATE.get(round_name)
    if not pstate:
        return ""

    step_config = _load_step_config()
    current_step = pstate.get("current_step", "")
    if not current_step:
        return ""

    # 获取当前 Step 在 step_config 中的索引
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    try:
        idx = step_keys.index(current_step)
    except ValueError:
        return ""

    if idx + 1 >= len(step_keys):
        return ""  # 已是最后一步

    next_step = step_keys[idx + 1]
    new_sha = result.get("new_sha", "")

    # 1. 状态机推进
    pstate["current_step"] = next_step
    pstate["last_output_sha"] = new_sha
    # 更新 Task state（复用现有 _cmd_task_update 逻辑）
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    for t in tasks:
        if t.get("name") == current_step and t.get("state") != p.TaskState.COMPLETED.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.COMPLETED.value,
                "output": new_sha,
            })
        if t.get("name") == next_step and t.get("state") == p.TaskState.PENDING.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.WORKING.value,
            })

    # 2. 清理旧 ACK FAILED 标记
    old_ack_key = f"{round_name}/{current_step}"
    if old_ack_key in _step_ack_states:
        if _step_ack_states[old_ack_key].get("state") == "FAILED":
            _step_ack_states.pop(old_ack_key, None)
            logger.info("[R65] 清除 %s 的 FAILED 标记（git sync 发现新产出）", old_ack_key)

    # 3. 广播自动同步消息
    ws_id = pstate.get("ws_id", "")
    commit_short = new_sha[:7] if new_sha else "?"
    mode = result.get("mode", "auto")
    mode_label = "" if mode == "default" else f"（{mode} 匹配）"

    msg = (
        f"💻 {round_name} {current_step} → {next_step} 已自动同步\n"
        f"  commit: {commit_short}{mode_label}\n"
        f"→ @{next_step} 到你了！"
    )

    if ws_id:
        pm_name = config.PIPELINE_PM_NAME
        _persist_broadcast(ws_id, pm_name, msg)
        payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": pm_name, "from": pm_name,
            "content": msg, "ts": time.time(),
        })
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(payload)
                        elif hasattr(conn, "send"):
                            await conn.send(payload)
                    except Exception:
                        pass

    # 4. 点名下一角色（复用 R63 @role_name → @bot_name 机制）
    next_role = step_config[next_step].get("role", "")
    if next_role:
        cards = _load_agent_cards()
        ws_obj = ws_mod.get_workspace(ws_id) if ws_id else None
        if ws_obj and cards:
            matched = _find_agents_by_role(next_role, ws_obj.members, cards)
            users = auth.get_users()
            for aid in matched:
                name = users.get(aid, {}).get("name", aid[:12])
                mention = f"@{name} 🏗️ {round_name} {next_step} 到你了！"
                # 通过 WS Bridge 发送点名消息
                mention_payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": mention, "ts": time.time(),
                })
                for conn in list(_connections.get(aid, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(mention_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(mention_payload)
                    except Exception:
                        pass

    # 5. 启动下一 Step timeout_tracker 倒计时
    if _ENABLE_R63_TIMEOUT:
        timeout_min = step_config.get(next_step, {}).get("timeout_minutes", 20)
        timeout_tracker.start_timer(round_name, next_step, timeout_min)

    logger.info("[R65] 管线 %s 已自动推进：%s → %s (sha=%s)",
                round_name, current_step, next_step, commit_short)
    return msg
```

#### 2.3.1 与 `!step_complete` 的关系

| 场景 | `!step_complete` | Git 自动同步 | 结果 |
|:-----|:---------------:|:------------:|:-----|
| bot 调用了命令 | ✅ 正常推进 | 跳过（last_sha 已是最新） | ✅ 正常 |
| bot 推码没调命令 | ⏳ 未调用 | ✅ 自动检测推进 | ✅ 管线继续 |
| 有人调命令但没推码 | ✅ 正常推进 | 不检测（同 SHA） | ✅ 正常 |
| 两者同时触发 | ✅ 命令优先（2s buffer） | sync 后判断已最新→skip | ✅ 安全 |

---

### 2.4 A4 — `!pipeline_status` 增强（handler.py 修改）

#### 2.4.1 改动位置

在 `_cmd_pipeline_status()` 函数尾部 return 之前，添加：

```python
# ── R65 A4: Git sync status line ──
if config.ENABLE_GIT_SYNC and _GIT_SYNC_TASK is not None:
    last_sync_ts = pstate.get("_last_git_sync_ts", 0)
    if last_sync_ts:
        delta = int(time.time() - last_sync_ts)
        sync_display = f"{delta}s 前" if delta < 120 else f"{delta // 60}m 前"
    else:
        sync_display = "—"
    branch = pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH) \
             if (_PIPELINE_CONFIG.get(round_name, {}) else config.GIT_SYNC_BRANCH)
    lines.append(f"  🔄 Git 同步: 启用 ✅（最后检查: {sync_display}, {branch}）")
```

#### 2.4.2 输出示例

```
📊 **R65 管线状态**
  📎 WORK_PLAN: https://raw.githubusercontent.com/...
  模式: 🚀 auto
  成员: 🟢小周 · 🟢泰虾 · 🟢小谷
| Step | 角色 | 状态 |
|:----:|:----:|:----:|
| 1 | PM | ✅ 已完成 |
| 2 | Arch | ✅ 已完成 |
| 3 | Dev | ◀ 当前 |
  🔄 Git 同步: 启用 ✅（最后检查: 45s 前, dev）
```

---

### 2.5 A5 — config.py 新增配置

在 R63 配置块后追加（L122 后）：

```python
# ── R65: Git pipeline sync ──────────────────────────────────
# 管线 git 同步自动检测开关
ENABLE_GIT_SYNC: bool = os.environ.get("R65_ENABLE_GIT_SYNC", "1") == "1"
# git 检测间隔（秒）
GIT_SYNC_INTERVAL: int = int(os.environ.get("R65_GIT_SYNC_INTERVAL", "120"))
# 默认工作分支
GIT_SYNC_BRANCH: str = os.environ.get("R65_GIT_SYNC_BRANCH", "dev")
# 兜底开关（任意新 commit 即推进）
GIT_SYNC_FALLBACK: bool = os.environ.get("R65_GIT_SYNC_FALLBACK", "1") == "1"
# Git 仓库本地路径
REPO_PATH: str = os.environ.get("R65_REPO_PATH", "/opt/data/ws-bridge")
```

---

### 2.6 B1 — `!step_complete` 无 `--output` 自动 SHA（handler.py 修改）

#### 2.6.1 改动位置

`_cmd_step_complete()` L1940 处（`output_ref = params.get("output", "")` 后）：

```python
# ── R65 B1: Auto-detect SHA when --output is missing ──
if not output_ref and config.ENABLE_GIT_SYNC:
    try:
        branch = config.GIT_SYNC_BRANCH
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "-1", "--format=%H", f"origin/{branch}",
            cwd=config.REPO_PATH,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0:
            sha = stdout.decode().strip()
            if sha:
                output_ref = sha
                logger.info("[R65 B1] 自动检测最新 SHA: %s", sha)
        else:
            logger.warning("[R65 B1] git log 失败: %s", stderr.decode().strip())
    except Exception as e:
        logger.warning("[R65 B1] 自动检测 SHA 异常: %s", e)

if not output_ref:
    return "❌ 缺少 --output <sha>，且无法自动检测最新 commit"
```

---

### 2.7 C1 — ACK 超时不标 FAILED（handler.py 修改）

#### 2.7.1 改动位置

`_ack_timeout_task()` L1372-1377 处：

```python
async def _ack_timeout_task(ack_key: str) -> None:
    """30-second ACK timeout detection.

    R65 C1: ACK 超时不标记 FAILED，改为 ack_timeout 等待标记。
    只有当 git sync + timeout_tracker 都无产出时才标记真正 FAILED。
    """
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    state = _step_ack_states.get(ack_key, {})
    if state.get("state") in ("SENT", "DELIVERED"):
        # ── R65 C1: ACK 超时 → 标记 ack_timeout（不标 FAILED）──
        state["state"] = "ack_timeout"
        logger.info("[R65 C1] ACK 超时: %s (agent=%s) — 等待 git 产出，不标 FAILED",
                    ack_key, state.get("agent_id", "?"))
        # 仅发送信息性消息，不触发 escalation
        await _send_ack_timeout_info(ack_key, state)
```

#### 2.7.2 新增 `_send_ack_timeout_info()`

```python
async def _send_ack_timeout_info(ack_key: str, state: dict) -> str:
    """ACK 超时信息通知（非告警）。"""
    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    info = (
        f"⏰ [ACK 未响应] {round_name} {step_name}\n"
        f"  目标: {display_name} — 30s 内未回复 ACK\n"
        f"  状态: ⚠️ 等待 git 产出（不标记失败）\n"
        f"  Git sync 将自动检测并推进"
    )

    # 广播到工作室
    for rname, pstate in _PIPELINE_STATE.items():
        if rname == round_name:
            ws_id = pstate.get("ws_id", "")
            if ws_id:
                pm_name = config.PIPELINE_PM_NAME
                _persist_broadcast(ws_id, pm_name, info)
                payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": info, "ts": time.time(),
                })
                ws_obj = ws_mod.get_workspace(ws_id)
                if ws_obj:
                    for member_id in ws_obj.members:
                        for conn in list(_connections.get(member_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(payload)
                                elif hasattr(conn, "send"):
                                    await conn.send(payload)
                            except Exception:
                                pass
            break

    logger.info("[R65 C1] ACK 超时信息: %s (target=%s)", ack_key, display_name)
    return info
```

#### 2.7.3 真正 FAILED 的判断逻辑

```
ACK 超时 + 无新 git commit + timeout_tracker 超时
    → _watchdog_scan 中判断:
        if step_ack_state == "ack_timeout"
        and no new commit from git sync
        and timeout_tracker.is_expired()
            → 此时才标记真正 FAILED
```

该判断逻辑不在本轮实现（超出 scope），但为未来扩展预留钩子：
- ACK 超时状态 `ack_timeout` 可供后续 `_watchdog_scan` 读取
- 当前行为：ACK 超时后仅提示等待，管线不会被阻塞在 FAILED 状态

---

## 3. 实现顺序与依赖

| 实现顺序 | 模块 | 前置依赖 | 备注 |
|:--------:|:-----|:---------|:------|
| 1️⃣ | config.py 追加配置 | 无 | 最先，其他模块需要 config 常量 |
| 2️⃣ | pipeline_sync.py 新建 | config.py | 纯新文件，可独立测试 |
| 3️⃣ | A2 watchdog 集成 (handler.py) | pipeline_sync.py | 导入新模块 |
| 4️⃣ | A3 _auto_advance_pipeline (handler.py) | A2 | 推进状态机逻辑 |
| 5️⃣ | A4 status 增强 (handler.py) | A2 | 显示 git sync 信息 |
| 6️⃣ | B1 step_complete 增强 (handler.py) | config.py | 自动检测 SHA |
| 7️⃣ | C1 ACK 超时优化 (handler.py) | 无 | 独立改动 |

**并行可行性：** #1 与 #7 可并行，#3 与 #6 可并行，#2 完成后 #3/#4/#5 可并行。

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `git fetch` 在网络差时阻塞 | watchdog 卡住 | asyncio.wait_for 超时 10s，失败静默跳过 |
| 多人同时推码 → 批量提交 | 单次 sync 检测多个 commit | 按 commit 时间逐个匹配，一次只推进一 Step |
| git 凭证不可用 | 检测始终失败 | 退化到纯手动（ENABLE_GIT_SYNC=false） |
| 兜底规则太宽松 | 错误推进到无关角色 | 下一角色会检查 scope 后拒绝（`!step_reject`） |
| 新文件导入循环 | handler.py 导入 pipeline_sync.py | 单向导入：handler → pipeline_sync，无反向引用 |
| server 重启时 asyncio task 丢失 | git sync loop 停止 | handler 初始化时调用 `_ensure_git_scan()` |

---

## 5. 不变承诺

以下模块**不在此轮修改**：

| 模块 | 原因 |
|:-----|:------|
| `gateway-plugin/` | Gateway 层不改，纯内部逻辑 |
| `server/agent_card.py` | Agent Card schema R63 已定 |
| `server/timeout_tracker.py` | 倒计时模块不动，只复用其 API |
| Web UI / 前端 | 纯服务端改动 |
| 新外部依赖 | 纯 stdlib + git CLI |

---

## 6. 脱敏检查

- [ ] `docs/R65/R65-tech-plan.md` 零内部名残留
- [ ] 所有角色名使用角色代号（arch/dev/review/qa/pm/admin）
- [ ] 所有 git remote 引用使用 `origin`（不暴露内部 URL）
- [ ] handler.py diff 零内部信息泄露

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-02 | 初稿，基于 R65 需求文档 v1.0 ✅ + WORK_PLAN v1.0 ✅ |
