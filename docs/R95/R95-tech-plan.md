---
pipeline:
  name: "R95 — Auto Pipeline 停止命令 🛑"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R95/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R95/R95-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: pipeline_stop 技术方案
      - step: step3
        role: developer
        title: 实现 pipeline_stop 命令
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 功能测试
      - step: step6
        role: admin
        title: 部署到生产
  steps:
    step2:  { role: architect,  title: pipeline_stop 技术方案 }
    step3:  { role: developer,  title: 实现 pipeline_stop 命令 }
    step4:  { role: reviewer,   title: 代码审查 }
    step5:  { role: qa,         title: 功能测试 }
    step6:  { role: admin,      title: 部署到生产 }
  workspace:
    members:
      architect: { mention_keyword: "architect;架构师" }
      developer: { mention_keyword: "developer;开发" }
      reviewer:  { mention_keyword: "reviewer;审查" }
      qa:        { mention_keyword: "qa;测试" }
      admin:     { mention_keyword: "admin;运维" }
---

# R95 技术方案 — `!pipeline_stop` 管线停止命令 🛑

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R95/R95-product-requirements.md` v2.0
> **改动文件：** `server/handler.py` · `server/pipeline_context.py` · `server/auto_router.py`

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ 状态机扩展：新增 `stopped` 状态](#️-状态机扩展新增-stopped-状态)
3. [🅱️ `_cmd_pipeline_stop` handler](#️-_cmd_pipeline_stop-handler)
4. [🅲 AutoRouter 停止信号检测](#️-autorouter-停止信号检测)
5. [🅳 pipeline_status 扩展](#️-pipeline_status-扩展)
6. [边界条件与异常处理](#6-边界条件与异常处理)
7. [不涉及的部分](#7-不涉及的部分)
8. [改动对照表](#8-改动对照表)
9. [验收清单](#9-验收清单)

---

## 1. 改动总览

### 1.1 新增命令

```python
!pipeline_stop R<N>
# 示例:
!pipeline_stop R94
```

| 属性 | 值 |
|:-----|:----|
| 命令名 | `pipeline_stop` |
| 参数 | `R<N>` — 管线轮次名 |
| 权限 | 仅该管线的发起者（`pipeline_context.creator_id`） |
| 幂等 | ✅ 重复 stop → `✅ 已停止（无需操作）` |
| 状态转换 | `running` → `stopped` |
| 行为 | 清空待发送队列 + 取消超时等待 + 标记停止 |

### 1.2 改动文件

| 文件 | 改动 | 估算行数 |
|:-----|:-----|:--------:|
| `server/pipeline_context.py` | 新增 `PipelineStatus.STOPPED` 枚举值 + `from_dict` 兼容 | +3 |
| `server/handler.py` | 新增 `_cmd_pipeline_stop()` ~45 行 + 命令注册 | +50 |
| `server/auto_router.py` | `_handle_message` 新增停止信号检测 + `_cancel_pipeline` 方法 | +25 |
| **合计** | **3 文件** | **~+78 行** |

---

## 2. 🅰️ 状态机扩展：新增 `stopped` 状态

### 2.1 状态流转图

```
                     !pipeline_start
        idle ─────────────────────────→ running
                                         │
                            ┌────────────┼──────────────┐
                            │            │              │
                      !pipeline_stop  完成(success)  超时/失败
                            │            │              │
                            ▼            ▼              ▼
                        stopped        success        failed
```

### 2.2 状态迁移表

| 当前状态 | 触发 | 新状态 | 动作 |
|:---------|:-----|:-------|:-----|
| `idle` | `!pipeline_start` | `running` | 创建管线，开始调度 |
| `running` | `!pipeline_stop` | `stopped` | 清空队列，取消调度 |
| `running` | 全部 Step 完成 | `success` | 自动通知 PM（已有） |
| `running` | 超时/异常 | `failed` | 已有逻辑 |
| `stopped` | `!pipeline_stop` (重复) | `stopped` | 幂等返回 |
| `stopped` | PM 手工派活完成 | `running` | AutoRouter 接管后重新激活 |

### 2.3 枚举定义

```python
# pipeline_context.py
class PipelineStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"   # 🆕 新增
```

### 2.4 from_dict 兼容

```python
# from_dict(): 未知状态兜底
try:
    status = PipelineStatus(d.get("status", "idle"))
except ValueError:
    status = PipelineStatus.STOPPED  # 安全兜底
```

---

## 3. 🅱️ `_cmd_pipeline_stop` handler

### 3.1 伪代码

```python
async def _cmd_pipeline_stop(sender_id: str, params: dict) -> str:
    # 1. 解析参数
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_stop R<N>"
    round_name = positional[0].upper()

    # 2. 获取管线上下文
    ctx = get_pipeline_context(round_name)
    if not ctx:
        return f"❌ 管线 {round_name} 不存在"

    # 3. 权限校验
    if ctx.creator_id != sender_id:
        return f"❌ 只有发起者可以 stop 此管线"

    # 4. 状态检查（幂等 + idle 拒绝）
    if ctx.status == PipelineStatus.STOPPED:
        return f"✅ Pipeline {round_name} 已停止（无需操作）"
    if ctx.status in (PipelineStatus.IDLE, PipelineStatus.SUCCESS, PipelineStatus.FAILED):
        return f"❌ Pipeline {round_name} 不在运行状态（当前: {ctx.status.value}）"

    # 5. 执行停止
    ctx.status = PipelineStatus.STOPPED
    save_pipeline_context(ctx)

    # 6. 通知 AutoRouter 停止调度
    await notify_auto_router_stop(round_name)

    # 7. 广播到 _admin（状态变更通知）
    try:
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": "broadcast",
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": f"🛑 Pipeline {round_name} 已停止（发起者: {sender_id[:12]}...）",
            "ts": time.time(),
        })
    except Exception:
        pass  # 不阻断 return

    return f"🛑 Pipeline {round_name} 已停止"
```

### 3.2 命令注册

```python
# _ADMIN_COMMANDS 或 _WORKSPACE_COMMANDS 中注册
_ADMIN_COMMANDS["pipeline_stop"] = {
    "min_role": 2,
    "handler": _cmd_pipeline_stop,
    "description": "停止 AutoRouter 管线调度。!pipeline_stop R<N>",
}
```

### 3.3 权限校验细节

| 场景 | 检查方式 | 结果 |
|:-----|:---------|:-----|
| 发起者 stop | `sender_id == ctx.creator_id` | ✅ 通过 |
| 非发起者 stop | sender_id 不匹配 | ❌ 拒绝 |
| PM/全局管理 stop | 项目负责人手动 inbox | ❌ 不额外开放 |

**设计理由：** 需求明确「仅发起者可 stop」。PM 如需强制停止，可自行关工作区 + 通知发起者。

---

## 4. 🅲 AutoRouter 停止信号检测

### 4.1 停止信号机制

AutoRouter 需要一个轻量级的停止信号检测，不需要完整的进程间通信：

**方案 A（推荐）：共享数据结构**

```python
# pipeline_context.py — 或独立模块
_stop_signals: dict[str, bool] = {}  # round_name → should_stop

def mark_stop(round_name: str):
    _stop_signals[round_name] = True

def should_stop(round_name: str) -> bool:
    return _stop_signals.pop(round_name, False)
```

**方案 B：直接检查 context 状态**

```python
# auto_router.py _dispatch_step() / _on_step_complete()
ctx = get_pipeline_context(round_name)
if ctx and ctx.status == PipelineStatus.STOPPED:
    logger.info("[AR] [%s] 管线已停止，跳过调度", round_name)
    return
```

**推荐方案 B** — 无额外状态同步，直接读取共享 context 状态。

### 4.2 AutoRouter 停止插入点

| 方法 | 停止检查时机 | 插入位置 |
|:-----|:------------|:---------|
| `_on_step_complete()` | 收到 ✅ 完成 → 检查 ⏭️ | 方法开头 |
| `_dispatch_step()` | 准备派活 → 检查 ⏭️ | 方法开头 |
| `_on_pipeline_ready()` | 管线就绪 → 检查 ⏭️ | 方法开头 |

### 4.3 待发送队列清空

当前 AutoRouter 没有显式的「待发送队列」——它是在收到消息后即时 `_dispatch_step` 的。**没有累积队列**。因此：

| 事项 | 状态 | 说明 |
|:-----|:----:|:-----|
| 即时派活 | ✅ 无需清空 | 每次收到完成消息直接派活下一步，无队列累积 |
| 已发出 inbox | 🔵 视为被吞 | 已发出的消息 AutoRouter 不再等待其响应 |
| step 超时等待 | 🔵 取消 | 停止时取消该管线的 pending 超时定时器 |

---

## 5. 🅳 pipeline_status 扩展

### 5.1 状态显示

```python
# pipeline_context.py _format_status() 或 handler.py _cmd_pipeline_status()
status_labels = {
    PipelineStatus.IDLE: "🟡 idle",
    PipelineStatus.RUNNING: "🟢 running",
    PipelineStatus.SUCCESS: "✅ success",
    PipelineStatus.FAILED: "❌ failed",
    PipelineStatus.STOPPED: "🛑 stopped",  # 🆕
}
```

### 5.2 输出格式

```
!pipeline_status R94
→ Pipeline R94:
  状态: 🛑 stopped
  发起者: ws_xxxx (小谷)
  Step 进度: 2/6 (completed: [1], current: step2)
  停止时间: 2026-07-11 10:30:00
```

---

## 6. 边界条件与异常处理

### 6.1 边界矩阵

| # | 场景 | 预期行为 | 测试方法 |
|:-:|:-----|:---------|:---------|
| B1 | stop 不存在的管线 | ❌ 管线不存在 | `!pipeline_stop R99` |
| B2 | stop idle 管线 | ❌ 不在运行状态 | `!pipeline_stop` → 立即 stop |
| B3 | 重复 stop | ✅ 幂等返回 | 连续两次 `!pipeline_stop R94` |
| B4 | 非发起者 stop | ❌ 权限拒绝 | 其他 bot 执行 `!pipeline_stop R94` |
| B5 | stop 后 bot 完成通知 | 🔵 AutoRouter 忽略 | bot 回复 ✅ 完成 → AR 检查状态 → 跳过 |
| B6 | stop 后 PM 手工派活 | ✅ AutoRouter 接管 | PM inbox → bot 完成 → AR 自动推进 |
| B7 | stop success/failed 管线 | ❌ 不在运行状态 | `!pipeline_stop` 对已结束管线 |
| B8 | 多管线并发 stop | ✅ 互不影响 | stop 只影响指定 round_name |
| B9 | 停止后工作区状态 | ✅ 保留 | 工作区内容不受 stop 影响 |

### 6.2 异常处理

| # | 异常场景 | 处理方式 | 对用户的影响 |
|:-:|:---------|:---------|:------------|
| E1 | context 保存失败 | 记录日志 warning，不影响返回值 | 状态回滚→重试 |
| E2 | `_broadcast_to_channel` 失败 | try/except 包裹，不阻断 return | 广播丢失，不影响主要功能 |
| E3 | AutoRouter 不在运行 | 发送信号无接收者 → context 状态已变 | 下次 AR 轮询自动生效 |

### 6.3 断点续跑流程

```
场景: R94 在 Step 3 卡死

1. !pipeline_stop R94
   → 状态变 stopped
   → AutoRouter 停止调度

2. PM 检查 !pipeline_status R94
   → 已完成: [step2]
   → 当前: step3 (stopped)

3. PM 从 dev 拉取 step3 的完成结果
   → 如果 arch 已完成但未回复 ✅ 完成

4. PM 给下一步 bot 发 inbox 派活
   → "请完成 step4 (review)..."

5. bot 回复 ✅ 完成
   → AutoRouter 收到完成通知
   → 检查 context → status=stopped → 忽略
   → PM 继续手动派活下一步...

6. 当 AutoRouter 收到 step4 完成（已不属于当前进度）
   → 需要在 _on_step_complete 中正确处理断点续跑的 step
```

**关键设计：** 断点续跑时，PM 手工派活后，bot 回复 `✅ 完成，已推 dev: xxxx`。AutoRouter 收到后：

1. 检查 `_round_progress[round_name]` 是否存在
2. 如果存在且 status=stopped → 是否需要自动重新激活？
3. **设计方案**：如果 `_round_progress[round_name]` 存在但当前没有活跃 step → 不自动恢复。PM 需要执行 `!pipeline_resume R<N>` 或类似操作。

但需求文档明确说了**不加 `--from` 或新命令**。所以：

**续跑逻辑：**
- PM 手工派活 → bot 完成 → 回复 ✅ 完成 → AutoRouter `_on_step_complete` 处理
- 如果该完成消息对应的 step 正好是当前进度 + 1 → AutoRouter 自动接管
- 否则（step 超出预期）→ 忽略（视为 stale 消息）

---

## 7. 不涉及的部分

| 功能 | 排除理由 |
|:-----|:---------|
| ❌ `--from` 参数 | 需求明确不新增 |
| ❌ 工作区自动关闭 | 使用已有 `!close_workspace` |
| ❌ bot 执行中断 | stop 停的是 AutoRouter，不是 bot |
| ❌ 自动保留现场 | 工作区和 bot 产出自然保留 |
| ❌ 定时自动停止 | 本次不实现，后续可扩展 |
| ❌ 适配多个发起者 | 仅限一人，无 workspace 管理员概念 |

---

## 8. 改动对照表

| 文件 | 改动内容 | 行数 | 备注 |
|:-----|:---------|:----:|:-----|
| `server/pipeline_context.py` | `PipelineStatus.STOPPED = \"stopped\"` | +1 | 枚举新增 |
| `server/pipeline_context.py` | `from_dict` 安全兜底 | +2 | ValueError → STOPPED |
| `server/handler.py` | `_cmd_pipeline_stop()` 函数 | +45 | 参数解析 → 权限 → 状态 → 广播 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 | +4 | `pipeline_stop` 命令注册 |
| `server/auto_router.py` | `_on_step_complete`/`_dispatch_step` 停止检查 | +15 | 3 处 method 开头检查 |
| `server/auto_router.py` | `_cancel_pipeline()` | +10 | 取消超时定时器 |
| **合计** | **3 文件** | **~+78** | 纯新增，零删除 |

---

## 9. 验收清单

| # | 验收项 | 验证方式 | 期望 |
|:-:|:-------|:---------|:-----|
| ✅-1 | running 管线 stop → stopped | `!pipeline_stop R<N>` + `!pipeline_status` | 状态变 `stopped` |
| ✅-2 | 已在执行的 bot 不受影响 | 运行中管线 stop → 观察 bot 输出 | bot 继续执行 |
| ✅-3 | idle 管线 stop → 报错 | 新建 idle 管线后 stop | ❌ 不在运行状态 |
| ✅-4 | 重复 stop → 幂等 | 连续两次 stop | ✅ 已停止（无需操作） |
| ✅-5 | 非发起者 stop → 拒绝 | 其他 bot 执行 stop | ❌ 只有发起者可以 |
| ✅-6 | 已结束管线 stop → 报错 | success/failed 后 stop | ❌ 不在运行状态 |
| ✅-7 | pipeline_status 显示 stopped | stop 后查询 | `🛑 stopped` |
| ✅-8 | stop 后其他管线不受影响 | 另一管线正常推进 | 互不干扰 |
| ✅-9 | 断点续跑可用 | PM 派活 → bot 完成 → AR 接管 | step N+1 自动推进 |
| ✅-10 | 零删除，纯新增 | `git diff --stat` | 仅 + 行 |
