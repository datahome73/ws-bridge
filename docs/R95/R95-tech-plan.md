# R95 技术方案 — Auto Pipeline 停止命令 🛑

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R95/R95-product-requirements.md` v2.0
> **改动文件：** `server/handler.py` · `server/auto_router.py`
> **净行数：** `handler.py ~+80` · `auto_router.py ~+30` · 合计 **~+110 行**
> **新增命令：** `!pipeline_stop R<N>` — 仅 1 条命令

---

## 目录

1. [状态机设计](#1-状态机设计)
2. [🅰️ `_cmd_pipeline_stop` Handler](#️-_cmd_pipeline_stop-handler)
3. [🅱️ AutoRouter 停止信号](#️-autorouter-停止信号)
4. [🅲 `!pipeline_status` 显示 stopped](#️-pipeline_status-显示-stopped)
5. [编码预检表](#5-编码预检表)
6. [验收清单](#6-验收清单)

---

## 1. 状态机设计

### 1.1 当前状态模型

```python
# handler.py L63 — 全局状态
_PIPELINE_STATE: dict[str, dict] = {}
# 每个管线条目：
# {
#   "active": True,            # bool — 目前是二元活跃标志
#   "current_step": "step2",   # str
#   "ws_id": "ws:xxx",         # str
#   "started_at": 1234567890,  # float
#   "triggerer_id": "ws_xxx",  # str — 发起者 agent_id
#   "mode": "auto",            # str
# }
```

### 1.2 新增 `stopped` 字段

**不改 `active` 字段（保持向后兼容）**，新增 `stopped` 布尔标志：

```python
# 改动后：
{
    "active": True,           # 不变
    "stopped": False,         # 🆕 新增
    "current_step": "step2",
    ...
}
```

| 状态组合 | 含义 | `!pipeline_stop` 行为 | `!pipeline_status` 显示 |
|:---------|:-----|:----------------------|:------------------------|
| `active=True, stopped=False` | 正常运行 | 改为 `stopped=True` | 正常显示 |
| `active=True, stopped=True` | 已停止 | 幂等提示 | 显示 🛑 |
| `active=False` | 已结束/清理 | 报错「不在运行状态」 | 不显示 |

### 1.3 状态流转

```
!pipeline_start  ──────────→  active=True, stopped=False
                                    │
                          !pipeline_stop R<N>
                                    │
                                    ▼
                            active=True, stopped=True
                                    │
                          !close_workspace / 清理
                                    │
                                    ▼
                            active=False（清除）
```

---

## 2. 🅰️ `_cmd_pipeline_stop` Handler

### 2.1 改动坐标

| # | 文件 | 位置 | 内容 | 预估行数 |
|:-:|:-----|:----:|:-----|:--------:|
| A-1 | `handler.py` | 新增函数（`_cmd_step_complete` 附近） | `_cmd_pipeline_stop()` 函数 | ~50 |
| A-2 | `handler.py` | `_ADMIN_COMMANDS` dict | 注册 `"pipeline_stop"` 条目 | ~5 |
| A-3 | `handler.py` | `_cmd_pipeline_start` ~L2750 | `_set_pipeline_state()` 调用增加 `"stopped": False` | ~1 |
| A-4 | `handler.py` | `_activate_pipeline` ~L2881 | 同上，增加 `"stopped": False` | ~1 |

### 2.2 `_cmd_pipeline_stop` 函数设计

```python
# 伪代码
async def _cmd_pipeline_stop(sender_id: str, params: dict) -> str:
    round_name = params.get("_positional", [""])[0]  # !pipeline_stop R<N>
    if not round_name.startswith("R"):
        return "❌ 用法: !pipeline_stop R<N>"

    pstate = _PIPELINE_STATE.get(round_name)
    if not pstate or not pstate.get("active"):
        return f"❌ Pipeline {round_name} 不在运行状态"

    # 权限：仅发起者可 stop
    if pstate.get("triggerer_id") != sender_id:
        return f"❌ 只有发起者可以 stop 此管线"

    # 幂等：已 stopped
    if pstate.get("stopped"):
        return f"✅ Pipeline {round_name} 已停止（无需操作）"

    # 设置 stopped 标志
    pstate["stopped"] = True

    # 通知 AutoRouter（通过 shared 变量或 broadcast）
    _signal_pipeline_stop(round_name)    # 见 🅱️

    return f"🛑 Pipeline {round_name} 已停止"
```

### 2.3 命令注册

```python
_ADMIN_COMMANDS = {
    # ... 原有命令 ...
    "pipeline_stop": {
        "handler": _cmd_pipeline_stop,
        "min_role": 1,               # 所有已认证 bot 可用
        "workspace_scope": False,     # 全局命令
        "usage": "!pipeline_stop R<N>",
    },
}
```

**权限说明：** `min_role=1` 可让任意已认证 bot 尝试 stop，但 handler 内部会校验 `triggerer_id`（仅发起者）。外部不设 `min_role` 守卫，因为发起者可能是任意角色（P1 观察者也能发 `!pipeline_start`）。

---

## 3. 🅱️ AutoRouter 停止信号

### 3.1 当前 AutoRouter 循环

```python
# auto_router.py L65-112
self._running = False  # 全局运行标志
# 主循环 while self._running:
#   监听消息 → 处理 → 超时检测 → 派活
```

### 3.2 改动方案

```python
# auto_router.py 🆕 新增
_STOP_SIGNAL: dict[str, float] = {}  # round_name -> timestamp

def signal_pipeline_stop(round_name: str) -> None:
    """从 handler.py 调用，通知 AutoRouter 停止指定管线。"""
    _STOP_SIGNAL[round_name] = time.time()

def is_pipeline_stopped(round_name: str) -> bool:
    """检查管线是否已被 stop。"""
    return round_name in _STOP_SIGNAL
```

### 3.3 AutoRouter 改动

| # | 文件 | 位置 | 内容 | 预估行数 |
|:-:|:-----|:----:|:-----|:--------:|
| B-1 | `auto_router.py` | 模块级 | `_STOP_SIGNAL` dict + `signal_pipeline_stop()` + `is_pipeline_stopped()` | ~10 |
| B-2 | `auto_router.py` | `_handle_message()` 收到 step_complete 后 | 检查 `is_pipeline_stopped()` → 跳过自动推进 | ~5 |
| B-3 | `auto_router.py` | `_check_step_timeouts()` 中 | 检查 `is_pipeline_stopped()` → 跳过超时告警 | ~5 |
| B-4 | `auto_router.py` | `_on_pipeline_ready()` 中 | 检查 `is_pipeline_stopped()` → 跳过派活 | ~5 |
| B-5 | `handler.py` | `_cmd_pipeline_stop()` 末尾 | 调用 `auto_router.signal_pipeline_stop(round_name)` | ~1 |

### 3.4 停止点一览

| 检查点 | 函数 | 无 signal 时行为 | signal 后行为 |
|:-------|:-----|:-----------------|:--------------|
| step_complete 后推进下一步 | `_handle_message()` → 收到 `MSG_STEP_COMPLETE` | 自动加载 topology 推下一步 | 跳过，不做任何推进 |
| 超时检测 | `_check_step_timeouts()` | 超时 → 通知 PM | 跳过，不告警 |
| 初始派活 | `_on_pipeline_ready()` | 加载 topology + 派 Step 2 | 跳过，不派活 |

---

## 4. 🅲 `!pipeline_status` 显示 stopped

### 4.1 改动

`_cmd_pipeline_status()` ~L4250 附近，在 `pstate.get("active")` 过滤之后，增加：

```python
# -- R95: Stopped marker --
if pstate.get("stopped"):
    lines.append(f"  🛑 **管线已停止** — 不再自动推进新步骤")
```

### 4.2 状态行格式

```
📊 **R95 管线状态**
  🛑 管线已停止 — 不再自动推进新步骤
  Step: step2 ⏳ — architect ◀ 当前
```

---

## 5. 编码预检表

| ID | 文件 | 位置 | 改动 | 行数 |
|:---|:-----|:----:|:-----|:----:|
| A-1 | `handler.py` | 新增函数（`_cmd_step_complete` ~L3067 后） | `_cmd_pipeline_stop()` | ~50 |
| A-2 | `handler.py` | `_ADMIN_COMMANDS` ~L4740 | 注册 `"pipeline_stop"` | ~5 |
| A-3 | `handler.py` | `_cmd_pipeline_start` ~L2750 | state 增加 `"stopped": False` | +1 |
| A-4 | `handler.py` | `_activate_pipeline` ~L2881 | state 增加 `"stopped": False` | +1 |
| A-5 | `handler.py` | `_cmd_pipeline_stop()` 末尾 | import auto_router + `signal_pipeline_stop()` | +1 |
| B-1 | `auto_router.py` | 模块级全局定义处 ~L65 | `_STOP_SIGNAL` dict + 2 个辅助函数 | ~10 |
| B-2 | `auto_router.py` | `_handle_message()` ~L350 | 收到 step_complete 后检查 stop | ~5 |
| B-3 | `auto_router.py` | `_check_step_timeouts()` ~L280 | 检查 stop | ~5 |
| B-4 | `auto_router.py` | `_on_pipeline_ready()` ~L200 | 检查 stop | ~5 |
| C-1 | `handler.py` | `_cmd_pipeline_status()` ~L4250 | stopped 标记显示 | ~3 |
| **合计** | **2 文件** | | | **~+86 行** |

---

## 6. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| ✅-1 | running 管线 stop → 状态变 `stopped` | `!pipeline_stop R<N>` → `🛑 Pipeline R<N> 已停止` |
| ✅-2 | stop 后 AutoRouter 不推进新 step | 观察日志无 `_handle_message` → 推进 |
| ✅-3 | stop 时已在执行的 bot 不受影响 | 正在执行的 bot 继续正常输出 |
| ✅-4 | 待发送 inbox 被清空 | 无新 `MSG_TASK_ASSIGN` 消息发出 |
| ✅-5 | 已发出的 inbox 不等超时 | 无超时告警 |
| ✅-6 | idle 管线 stop → 报错 | `❌ Pipeline R<N> 不在运行状态` |
| ✅-7 | 重复 stop → 幂等 | `✅ Pipeline R<N> 已停止（无需操作）` |
| ✅-8 | 非发起者 stop → 权限拒绝 | `❌ 只有发起者可以 stop 此管线` |
| ✅-9 | stop 后其他管线不受影响 | `!pipeline_status` 只显示受影响管线的 🛑 |
| ✅-10 | `!pipeline_status` 显示 `🛑` | 管线条目含 🛑 标记 |
| ✅-11 | 断点续跑：PM inbox 派活 + AutoRouter 接管 | 手动派活 → bot 回复 → auto 推进后续 step |

---

*技术方案编写: 🏗️ 架构师 · 2026-07-11*
