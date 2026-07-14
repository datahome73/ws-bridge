# R111 Step 2 — ## 命令启动管线技术方案

> **轮次：** R111
> **版本：** v1.0
> **日期：** 2026-07-15
> **审核：** [R111 需求文档](R111-product-requirements.md)
>
> **设计角色：** 小开（架构师）
> **实现角色：** 爱泰（开发工程师）

---

## 一、概述

在 `_handle_server_relay` 中新增 `##` 前缀规则，利用已有 `PipelineContext/auto_dispatch` 机制实现简洁可靠的管线启动入口。

### 改动范围

| 文件 | 改动类型 | 说明 |
|:-----|:---------|:------|
| `docs/R111/R111-tech-plan.md` | ✅ 新增 | 本技术方案 |
| `server/ws_server/main.py` | ✅ 修改 | 3 行拦截插入 + ~50 行新函数 |

### 零改动文件

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | `PipelineContextManager.create()` / `transition_to()` 全复用 |
| `commands/pipeline.py` | `DEFAULT_STEPS` 引用，不复用命令处理器 |
| `command_utils.py` | `_refresh_role_agent_map()` 直接调用 |
| `config.py` | `PIPELINE_PM_AGENT_ID` / `AUTO_DISPATCH_ENABLED` 已存在 |
| `pipeline_auto_starter.py` | 废弃，不碰 |

---

## 二、`##` 拦截插入点

**位置：** `_handle_server_relay` 中，to_agent 派活路由分隔行（L2634）之后、PM 守卫（L2636）之前。

```
L2634  # ═══════════════════════════════════════════
      ↓ 插入
   # ═══ R111: ## 命令 ═══
   if content.startswith("##"):
       return await _handle_hash_cmd(content, agent_id, ws)
   # ═══════════════════════════════════════════
      ↑ 插入
L2636  # ═══ 安全守卫: PM 误发 _inbox:server ═══
```

**为什么插在这里：**
- **在 PM 守卫之前** — `##` 命令不限制发送者身份（PM 或 bot 均可发），必须绕过 PM 拦截
- **在 to_agent 派活路由之后** — `##` 消息不带 to_agent，不会与派活混淆
- **在回路测试之后** — `test ✅` 优先级更高，不受影响

---

## 三、新增函数设计

### 3.1 `_handle_hash_cmd()` — 主分发函数

```python
async def _handle_hash_cmd(content: str, agent_id: str, ws) -> bool:
```

| 输入 | 说明 |
|:-----|:------|
| `content` | 原始消息内容（含 `##` 前缀） |
| `agent_id` | 发送者的 agent_id |
| `ws` | WebSocket 连接 |

**流程：**
1. `content.split("##")` → `["", "start", "R111", "k=v", ...]`
2. `parts[1]` → cmd（lower），`parts[2]` → round_name（upper）
3. `parts[3:]` → 解析 key=value
4. 按 cmd 分派到 `_handle_hash_start/status/stop/help`
5. `##help` 直接回复命令列表

### 3.2 `_handle_hash_start()` — 核心创建函数

```python
async def _handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool:
```

| 步骤 | 操作 | 异常处理 |
|:----:|:-----|:---------|
| 1 | `mgr.exists(round_name)` 防重复 | ✅ 已存在 → 返回 `{round} 管线已存在` |
| 2 | `_refresh_role_agent_map()` 刷新角色映射 | ✅ try/except |
| 3 | 从 `_ROLE_AGENT_MAP` + `_build_name_to_ws_map()` 填充 steps agent_id | ✅ 空 role 跳过 |
| 4 | 从 kv 提取 references（requirements_url / work_plan_url） | ✅ 可选字段 |
| 5 | `_build_default_templates()` 加载 6 步标准模板 | ✅ 硬编码 |
| 6 | 构建 `PipelineContext` → `mgr.set_context()` 落盘 | ✅ |
| 7 | `await mgr.transition_to(RUNNING)` | ✅ 从 INIT → RUNNING |
| 8 | `await _auto_dispatch(ctx, 1)` 派活 Step 1 | ✅ 受 AUTO_DISPATCH_ENABLED 控制 |
| 9 | 回复发送者 `✅ R111 管线已启动` | ✅ |

### 3.3 `_handle_hash_status()` / `_handle_hash_stop()`

| 函数 | 功能 | 不存在时 |
|:-----|:------|:---------|
| `_handle_hash_status` | `mgr.get()` → 拼装各步状态文本 → 回复 | ❌ `{round} 管线不存在` |
| `_handle_hash_stop` | `mgr.cancel()` → 状态 CANCELLED → 回复确认 | ❌ `{round} 管线不存在` |

### 3.4 辅助函数

| 函数 | 说明 |
|:-----|:------|
| `_build_default_templates()` | 返回 6 步标准模板 dict（复用 commands/pipeline.py L234-241） |
| `_build_name_to_ws_map()` | 从 `persistence.get_api_keys()` 构建 `display_name → ws_agent_id` 映射 |

---

## 四、PipelineContext 构建细节

```python
ctx = PipelineContext(
    round_name=round_name,
    task_kind=PipelineTaskKind.DEV,
    workspace_dir=Path(config.REPO_PATH) if hasattr(config, 'REPO_PATH') else Path("/opt/data/ws-bridge"),
    task_dir=Path(config.DATA_DIR) / "pipeline_tasks" / round_name,
    workspace_id="",
    pm_inbox_id=config.PIPELINE_PM_AGENT_ID,
    status=PipelineStatus.INIT,          # 初始 INIT，随后 transition_to(RUNNING)
    current_step=1,
    total_steps=6,                        # len(DEFAULT_STEPS)
    steps=steps_list,                     # 6 步填充 agent_id
    references=references,               # 从 kv 提取
    message_templates=templates,         # _build_default_templates()
    round_title=kv.get("round_title", round_name),
    created_by=agent_id,                 # 发送者 agent_id
)
```

> **注意：** 使用 `set_context()` + `transition_to()` 而非 `mgr.create()`，因为 create() 的 kwargs 机制不适合显式传 references/steps/message_templates。

---

## 五、状态回复格式

### ##status 回复
```
📊 R111 管线状态
├─ Step 1: ✅ 完成（小谷）
├─ Step 2: 🟢 执行中（小开）
├─ Step 3: ⬜ 待派活（爱泰）
├─ Step 4: ⬜ 待派活（小周）
├─ Step 5: ⬜ 待派活（泰虾）
└─ Step 6: ⬜ 待派活（小爱）
```

### ##start 回复
```
✅ R111 管线已启动，Step 1 已派活到小谷
```

### ##stop 回复
```
🛑 R111 管线已停止（CANCELLED）
```

---

## 六、验证方法

```bash
# 确认插入点
grep -n 'R111.*##' server/ws_server/main.py

# 确认函数定义
grep -n 'def _handle_hash_cmd\|def _handle_hash_start\|def _handle_hash_status\|def _handle_hash_stop\|def _build_default_templates\|def _build_name_to_ws_map' server/ws_server/main.py

# 确认 PM 守卫前已拦截（L2636 附近）
grep -n 'PM 误发' server/ws_server/main.py
```

---

## 七、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-15 | 初稿 |
