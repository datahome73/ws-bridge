# R111 — ## 命令启动管线：简洁可靠的自动派活入口 🚀

> **版本：** v1.0
> **日期：** 2026-07-14
> **状态：** 📝 需求文档
> **轮次：** R111
> **优先级：** P0
> **前置条件：** R110 全闭环已上线 ✅

---

## 一、背景

### 1.1 问题

R88→R110 一直在尝试一条复杂的自动化路径：

```
WORK_PLAN.md frontmatter 解析
  → PipelineContextManager.from_work_plan()
    → _cmd_pipeline_start（命令处理器）
      → PipelineAutoStarter（Git poll 后台循环）
      → PM 守卫绕过
```

这条路线产生了大量 bug（frontmatter 全角冒号、dict vs PipelineContext 类型不匹配、logger 未定义、Agent card key 桥接失败、PM 守卫拦截、PipelineAutoStarter 被禁用……）。**根源在于用「文件解析 + 命令触发」来启动管线，层层叠加不稳定。**

### 1.2 已有的成熟机制

`_handle_server_relay` 在 `_inbox:server` 通道上已经有 4 条稳定的前缀规则：

| 规则 | 前缀 | 功能 | 从 R 开始稳定运行 |
|:----:|:-----|:-----|:-----------------:|
| 回路测试 | `test ✅` | 双向通信验证 | R96 |
| ACK | `收到 ✅` / `ACK ✅` | Bot 接活通知 | R87 |
| 完成 | `已完成 ✅` / `✅ 完成` | 完成推进 + _try_advance_pipeline | R87 |
| 退回/失败 | `退回 🔄` / `失败 ❌` | 异常通知 | R87 |

**这套前缀匹配机制从未出过问题。**

### 1.3 R111 方向

**利用同一套 `_inbox:server` 前缀匹配机制，加一条 `##start` 前缀规则来启动管线。** 管线数据直接通过消息内容传入，不依赖文件解析。

---

## 二、方案

### 2.1 `##start` 消息格式

```
##start##R{N}##key1=value1##key2=value2
```

| 段 | 示例 | 说明 |
|:--:|:-----|:------|
| `##start` | 固定 | 命令前缀，匹配器识别 |
| `##R{N}` | `##R111` | 轮次名，必须（第二段） |
| `##key=value` | `##requirements_url=https://...` | 可选，注入管线数据 |

**解析逻辑（`str.split("##")`）：**

```
"##start##R111##requirements_url=https://github.com/datahome73/ws-bridge/blob/main/docs/R111/R111-product-requirements.md"

split("##") →
["", "start", "R111", "requirements_url=https://github.com/datahome73/ws-bridge/blob/main/docs/R111/R111-product-requirements.md"]
  ↑ cmd   ↑ round_name   ↑ key=value
```

### 2.2 支持的命令集

| 命令 | 格式 | 功能 |
|:-----|:-----|:------|
| `##start` | `##start##R{N}##k=v` | 创建管线 + 派活 Step 1 |
| `##status` | `##status##R{N}` | 查询管线当前状态 |
| `##stop` | `##stop##R{N}` | 停止/归档管线 |
| `##help` | `##help` | 列出支持的命令 |

### 2.3 数据来源

`##start` 命令的管线数据，分两部分：

#### 从消息提取（由 PM 在消息中传入）

| 字段 | 提取方式 | 必要性 |
|:-----|:---------|:-------|
| `round_name` | 第二段（`R{N}`） | ✅ 必须 |
| `requirements_url` | `##requirements_url=...` | 可选 |
| `work_plan_url` | `##work_plan_url=...` | 可选 |
| `round_title` | `##round_title=...` | 可选，默认同 round_name |

#### 自动生成（代码硬编码，0 配置）

| 字段 | 来源 |
|:-----|:------|
| `total_steps=6` | `DEFAULT_STEP_ORDER` |
| 6 步定义（role/title） | `DEFAULT_STEPS` |
| 每步 agent_id | `_ROLE_AGENT_MAP[role]` + display_name 桥接 |
| `pm_inbox_id` | `config.PIPELINE_PM_AGENT_ID` |
| `message_templates` | 6 步标准模板组 |
| `role_agent_map` | `_refresh_role_agent_map()` 加载 |
| `created_by` | 发送消息的 agent_id |

### 2.4 `##start` 完整流程

```
PM → _inbox:server:
  "##start##R111##requirements_url=https://github.com/datahome73/ws-bridge/blob/main/docs/R111/R111-product-requirements.md"

_handle_server_relay:
  └─ content.startswith("##") → _handle_hash_cmd(content, agent_id, ws)
                                  ↓
                          解析: round_name="R111", kv={requirements_url: ...}
                                  ↓
                          防重复: PipelineContextManager.exists("R111")
                                  ↓
                          构建 PipelineContext:
                            ├─ round_name = "R111"
                            ├─ steps = DEFAULT_STEPS 填充 agent_id
                            ├─ references = {requirements_url, work_plan_url} 从消息提取
                            ├─ message_templates = 6步标准模板
                            └─ status = RUNNING, current_step = 1
                                  ↓
                          PipelineContextManager.create() → 写入 pipeline_contexts.json
                                  ↓
                          _auto_dispatch(ctx, 1) → 派活 Step 1 到小谷 inbox
                                  ↓
                          回复发送者: "✅ R111 管线已启动，Step 1 已派活"
```

### 2.5 后续推进（0 行改动）

```
小谷收到 Step 1 → 审核文档 → 回复 "已完成 ✅ R111 Step 1"
                                                    ↓
                        已有 relay 规则2 匹配 → _try_advance_pipeline
                                                    ↓
                        advance → _auto_dispatch Step 2→小开
                                                    ↓
                        小开→爱泰→小周→泰虾→小爱（已有全链路）
```

### 2.6 `##status` 流程

```
PM → _inbox:server: "##status##R111"

_handle_hash_cmd:
  ├─ round_name = "R111"
  ├─ ctx = mgr.get("R111")
  ├─ 构造状态回复:
     "📊 R111 管状态:
      Step 1: ✅ 完成（小谷）
      Step 2: 🟢 执行中（小开）
      Step 3: ⬜ 待派活（爱泰）
      ..."
  ├─ await _send(ws, ...) 回复发送者
```

### 2.7 `##stop` 流程

```
PM → _inbox:server: "##stop##R111"

_handle_hash_cmd:
  ├─ round_name = "R111"
  ├─ mgr.cancel("R111") 或 mgr.archive("R111")
  ├─ 回复: "🛑 R111 管线已停止"
```

---

## 三、改动点

### 3.1 `server/ws_server/main.py` — 3 行插入 + ~40 行新函数

**插入位置**（`_handle_server_relay` 中，L2633 `return True` 之后、L2636 PM 守卫之前）：

```python
# ═══ R111: ## 命令 ═══
if content.startswith("##"):
    return await _handle_hash_cmd(content, agent_id, ws)
# ═══════════════════════════════════════════
```

**新增函数 `_handle_hash_cmd()`：**

```python
async def _handle_hash_cmd(content: str, agent_id: str, ws) -> bool:
    """处理 ## 前缀命令。##start##R111##k=v"""
    parts = content.split("##")
    if len(parts) < 3:
        await _send(ws, {"type": "error", "error": "格式: ##start##R{N} 或 ##status##R{N} 或 ##stop##R{N}"})
        return True
    
    cmd = parts[1].lower()
    round_name = parts[2].upper()
    
    # 解析 key=value 数据段
    kv = {}
    for p in parts[3:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.strip()] = v.strip()
    
    if cmd == "start":
        return await _handle_hash_start(round_name, kv, agent_id, ws)
    elif cmd == "status":
        return await _handle_hash_status(round_name, agent_id, ws)
    elif cmd == "stop":
        return await _handle_hash_stop(round_name, agent_id, ws)
    elif cmd == "help":
        await _send(ws, {"type": "broadcast", "channel": f"_inbox:{agent_id}", ...})
        return True
    
    await _send(ws, {"type": "error", "error": f"未知 ## 命令: {cmd}"})
    return True
```

**`_handle_hash_start()`（核心，~30 行）：**

```python
async def _handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool:
    mgr = _ensure_pipeline_manager()
    if mgr.exists(round_name):
        await _send(ws, {"type": "error", "error": f"{round_name} 管线已存在"})
        return True
    
    command_utils._refresh_role_agent_map()
    
    # 1. 构建 steps（从 DEFAULT_STEPS 填充 agent_id）
    role_map = mgr.get_global_role_map() or dict(getattr(state, '_ROLE_AGENT_MAP', {}))
    name_to_ws = build_name_to_ws_map()  # display_name → ws_id
    steps_list = build_steps_with_agents(role_map, name_to_ws)
    
    # 2. 构建 references
    references = {}
    if kv.get("requirements_url"):
        references["requirements_url"] = kv["requirements_url"]
    if kv.get("work_plan_url"):
        references["work_plan_url"] = kv["work_plan_url"]
    
    # 3. 构建 message_templates（标准 6 步模板）
    templates = get_default_templates()
    
    # 4. 创建 PipelineContext
    ctx = PipelineContext(
        round_name=round_name,
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path(config.REPO_PATH) if hasattr(config, 'REPO_PATH') else Path("/opt/data/ws-bridge"),
        task_dir=Path(config.DATA_DIR) / "pipeline_tasks" / round_name,
        workspace_id="",
        pm_inbox_id=config.PIPELINE_PM_AGENT_ID,
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=len(DEFAULT_STEPS),
        steps=steps_list,
        references=references,
        message_templates=templates,
        round_title=kv.get("round_title", round_name),
        created_by=agent_id,
    )
    
    mgr.set_context(round_name, ctx)
    await mgr.transition_to(round_name, PipelineStatus.RUNNING)
    
    # 5. 自动派活 Step 1
    await _auto_dispatch(ctx, 1)
    
    # 6. 回复发送者
    await _send(ws, {"type": "broadcast", ...})
    return True
```

### 3.2 无需改动的文件

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | `PipelineContextManager.create()` / `transition_to()` 等全复用 |
| `commands/pipeline.py` | `DEFAULT_STEPS` 引用，不复用命令处理器 |
| `command_utils.py` | `_refresh_role_agent_map()` 直接调用 |
| `config.py` | `PIPELINE_PM_AGENT_ID` / `AUTO_DISPATCH_ENABLED` 已存在 |
| `pipeline_auto_starter.py` | 废弃，不碰 |

---

## 四、验收标准

### 4.1 ##start

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 1 | 发 `##start##R111` 到 `_inbox:server` → 创建 PipelineContext | `pipeline_contexts.json` 有 R111 条目 |
| 2 | Step 1 自动派活到小谷 inbox | 小谷收到 Step 1 审核消息 |
| 3 | 重复发同一 round → 返回错误，不重复创建 | 第二次 `##start##R111` → ❌ 管线已存在 |
| 4 | 非 PM 也能发 `##start`（不受 PM 守卫拦截） | 任意认证 agent 发送均被处理 |

### 4.2 ##status / ##stop

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 5 | `##status##R111` → 返回管线当前进度 | 回复含当前 step、各步状态 |
| 6 | `##stop##R111` → 停止管线 | 状态变为 CANCELLED |
| 7 | 管线不存在时返回有意义的错误 | `R111 管线不存在` |

### 4.3 后续推进兼容

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 8 | 小谷回复 `已完成 ✅ R111 Step 1` → 自动推进 Step 2 | 小开收到 Step 2 派活 |
| 9 | Step 2→6 全链路自动（与现有 _auto_dispatch 一致） | 管线自动执行至归档 |

---

## 五、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — ## 命令启动管线 |
