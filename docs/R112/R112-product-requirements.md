# R112 — Web 端管线进度可视化（Pipeline Dashboard）📊

> **版本：** v1.0
> **日期：** 2026-07-14
> **状态：** 📝 草稿（待项目负责人审核）
> **轮次：** R112
> **优先级：** P1
> **前置条件：** R111 全闭环已上线 ✅（## 命令启动管线 + `pipeline_contexts.json` 数据源）

---

## 一、背景

### 1.1 现状

R111 搭建了完整的 `##start/status/stop` 管线生命周期管理基础设施：

```
##start##R112 → PipelineContext 落盘 → pipeline_contexts.json
    ↓
_auto_dispatch Step 1 → 小谷 → "已完成 ✅" → Step 2→小开 → ...
    ↓
##status → 回复发送者（文本格式，仅命令行）
```

但当前进度查询只有 **命令行文本回复**（`##status##R{N}`），缺乏可视化界面。

### 1.2 问题

| # | 问题 | 影响 |
|:-:|:-----|:-----|
| 1 | `##status` 只有在 TG 上发消息才能查 | 项目负责人想随时看管线状态必须开 TG 发消息 |
| 2 | 无法一眼看清**所有管线的全局进度** | 要逐一查每个轮次 |
| 3 | 各 Agent 当前工作状态不可视 | 无法快速识别卡点 |
| 4 | 管线历史没有可视化归档 | 回溯困难 |

### 1.3 R112 目标

**在 Web 端新增「管线仪表盘」Tab，实现：**

- 📊 所有活跃管线一览（Step 进度条 + 各 Agent 状态）
- 🟢 每步的执行状态可视化（完成/执行中/待派活/失败）
- 👤 每步当前负责的 Agent
- 🔗 产出链接直达（方案 URL、代码 SHA、测试报告）
- ⏱️ 每步耗时/剩余超时显示
- 🔄 WebSocket 实时刷新（不刷新页面）

### 1.4 与 R111 的关系

```
R111: ## 命令启动管线 ← 基础设施（已完成）
  ↓
R112: Web 端管线可视化  ← 消费者（本轮）
  ↓
R113: 异常处理/自动化（下一轮方向）
```

R111 生成了 `pipeline_contexts.json` 数据源，AutoRouter 自动推进 Step、`_try_advance_pipeline` 更新状态——**R112 只需要读这些数据并在 Web 端渲染出来**，不改变管线核心逻辑。

---

## 二、数据来源

### 2.1 `pipeline_contexts.json`

R111 通过 `PipelineContextManager` 持久化管线数据到 `pipeline_contexts.json`（位于 `DATA_DIR/pipeline_contexts.json`）。

**每条管线记录的 Schema（已有字段，不需新增）：**

```json
{
  "R112": {
    "round_name": "R112",
    "status": "RUNNING",
    "current_step": 2,
    "total_steps": 6,
    "created_at": 1712345678.0,
    "updated_at": 1712345700.0,
    "created_by": "ws_f26e585f6479",
    "pm_inbox_id": "ws_f26e585f6479",
    "round_title": "Web 端管线可视化",
    "steps": [
      {"step": 1, "role": "需求分析师", "title": "需求调研与文档", "agent_id": "ws_f26e585f6479", "display_name": "小谷", "status": "completed", "completed_at": 1712345680.0, "artifact_url": "..."},
      {"step": 2, "role": "架构师", "title": "技术方案设计", "agent_id": "ws_3f7cdd736c1c", "display_name": "小开", "status": "working", "started_at": 1712345690.0},
      {"step": 3, "role": "开发工程师", "title": "编码实现", "agent_id": null, "display_name": "爱泰", "status": "pending"},
      {"step": 4, "role": "审查工程师", "title": "代码审查", "agent_id": null, "display_name": "小周", "status": "pending"},
      {"step": 5, "role": "测试工程师", "title": "测试验证", "agent_id": null, "display_name": "泰虾", "status": "pending"},
      {"step": 6, "role": "项目管理/调度员", "title": "部署上线", "agent_id": null, "display_name": "小爱", "status": "pending"}
    ],
    "references": {
      "requirements_url": "https://github.com/datahome73/ws-bridge/blob/dev/docs/R112/R112-product-requirements.md"
    }
  }
}
```

### 2.2 API 端点（新增）

| 端点 | 方法 | 返回 | 用途 |
|:-----|:----:|:-----|:-----|
| `/api/pipelines` | GET | 所有管线的摘要列表 | Tab 首页展示 |
| `/api/pipelines/{round_name}` | GET | 单条管线完整详情 | 点击展开详情 |
| `/ws` | — | WebSocket 推送 | 实时更新（复用现有连接） |

### 2.3 WebSocket 推送事件（新增事件类型）

在现有 WebSocket 协议中增加管线状态推送：

```json
{
  "type": "pipeline_update",
  "round_name": "R112",
  "current_step": 2,
  "status": "RUNNING",
  "step_status": "working",
  "agent_name": "小开"
}
```

触发时机：
- `##start##R{N}` 管线启动时 → 推 `status: running`
- `_auto_dispatch` 派活 → 推 `step_status: dispatched`
- `_try_advance_pipeline` 推进 Step → 推 `step_status: completed + next: working`
- `##stop##R{N}` → 推 `status: cancelled`

---

## 三、Web 端 UI 设计

### 3.1 新 Tab: 「📊 管线」

在 Web 顶部 Tab 栏新增 **「📊 管线」** Tab，排在「🏠 大厅」「📬 收件箱」「📜 历史」之后。

### 3.2 管线列表视图（默认）

```
┌─ 📊 管线仪表盘 ──────────────────────────────────────────────┐
│                                                                │
│  📋 活跃管线（2）                                               │
│                                                                │
│  ┌─ R112 ────────────────────────────────────────────────┐     │
│  │ 🟢 RUNNING  │  当前: Step 2/6  🕐 2分钟前更新           │     │
│  │ Progress:  ■■■■□□□□□  1/6 done                         │     │
│  │ Title: Web端管线进度可视化                                │     │
│  │ ───────────────────────────────────────────────           │     │
│  │ Step 1 ✅ 小谷  需求调研    [方案链接]  10:30 ✓          │     │
│  │ Step 2 🟢 小开  技术方案    [进行中...]  10:32           │     │
│  │ Step 3 ⬜ 爱泰  编码实现    —                             │     │
│  │ Step 4 ⬜ 小周  代码审查    —                             │     │
│  │ Step 5 ⬜ 泰虾  测试验证    —                             │     │
│  │ Step 6 ⬜ 小爱  上线部署    —                             │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                                │
│  ┌─ R111 ────────────────────────────────────────────────┐     │
│  │ ✅ COMPLETED │ 已归档  📅 2026-07-14                   │     │
│  │ Progress:  ■■■■■■■■■■  6/6 done                        │     │
│  │ ───────────────────────────────────────────────           │     │
│  │ Step 1 ✅ 小谷  ✅ 小开  ✅ 爱泰  ✅ 小周  ✅ 泰虾 ✅ 小爱  │     │
│  └──────────────────────────────────────────────────────┘     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 3.3 Step 状态图标

| 图标 | 状态 | 含义 |
|:----:|:-----|:------|
| ✅ | `completed` | 已完成 |
| 🟢 | `working` | 执行中 |
| ⏳ | `dispatched` | 已派活，等待 ACK |
| ⬜ | `pending` | 待派活 |
| 🔴 | `failed` | 失败/退回 |
| 🛑 | `cancelled` | 已取消 |

### 3.4 进度条配色

| 状态 | 颜色 |
|:-----|:-----|
| RUNNING | 🟢 绿色梯度 |
| COMPLETED | 🔵 蓝色实心 |
| CANCELLED/FAILED | 🔴 红色条纹 |
| INIT | ⚪ 灰色空心 |

### 3.5 响应式行为

- **桌面端**（>768px）：管线卡片网格布局，每行 2 列
- **移动端**（≤768px）：单列堆叠
- Step 标签自动折行

---

## 四、改动点

### 4.1 后端 — `server/web_ui/templates.py` 修改

| 改动 | 说明 | 估计行数 |
|:-----|:------|:--------:|
| 新增 API 端点 `GET /api/pipelines` | 从 `PipelineContextManager` 读取全量管线数据 | ~15 行 |
| 新增 API 端点 `GET /api/pipelines/{round_name}` | 单管线详情 | ~10 行 |
| 新增 WebSocket 推送类型 `pipeline_update` | 在 pipeline 状态变更点加入 `_broadcast_update` | ~10 行 |
| 新增 HTML/CSS/JS 管线 Tab 渲染 | 仪表盘 UI 组件 | ~150 行 |

**API 端点实现（templates.py 中新增路由）：**

```python
# routes
@routes.get("/api/pipelines")
async def handle_pipelines_list(request):
    """返回所有管线的摘要列表"""
    mgr = app.get("pipeline_manager")
    if not mgr:
        return web.json_response({"pipelines": []})
    all_ctx = await mgr.list_all()  # 时序异步读
    result = []
    for round_name, ctx in all_ctx.items():
        result.append({
            "round_name": round_name,
            "status": ctx.status.value if hasattr(ctx.status, 'value') else str(ctx.status),
            "current_step": ctx.current_step,
            "total_steps": ctx.total_steps,
            "round_title": getattr(ctx, 'round_title', round_name),
            "updated_at": ctx.updated_at,
            "steps": [
                {
                    "step": s.step,
                    "role": s.role_name or s.role,
                    "display_name": s.display_name or s.role,
                    "status": s.state.value if hasattr(s.state, 'value') else str(s.state),
                    "completed_at": getattr(s, 'completed_at', None),
                }
                for s in (ctx.steps or [])
            ]
        })
    return web.json_response({"pipelines": result})

@routes.get("/api/pipelines/{round_name}")
async def handle_pipeline_detail(request):
    """返回单条管线完整详情"""
    round_name = request.match_info["round_name"]
    mgr = app.get("pipeline_manager")
    if not mgr:
        return web.json_response({"error": "pipeline manager not available"}, status=500)
    ctx = mgr.get(round_name)
    if not ctx:
        return web.json_response({"error": f"pipeline {round_name} not found"}, status=404)
    return web.json_response(ctx.to_dict())
```

**WebSocket 推送（pipeline 状态变更触发点）：**

在每个修改管线状态的位置增加：
```python
# 在 _handle_hash_start / _try_advance_pipeline / _handle_hash_stop 中
await _broadcast_pipeline_update(round_name, status, current_step, step_status)
```

其中 `_broadcast_pipeline_update` 复用现有的 WebSocket 连接广播机制。

### 4.2 前端 — `server/web_ui/templates.py` 内嵌 HTML/CSS/JS

| 组件 | 说明 |
|:-----|:------|
| HTML | 管线 Tab 面板容器，与现有 Tab 渲染统一 |
| CSS | 管线卡片、进度条、Step 状态样式 |
| JS | 定期轮询 `/api/pipelines` + WebSocket 实时更新 |

### 4.3 后端 — `server/ws_server/main.py` 插入广播

| 位置 | 插入点 | 代码 |
|:-----|:-------|:-----|
| `_handle_hash_start()` | Step 9（回复后） | `asyncio.ensure_future(_broadcast_pipeline_update(...))` |
| `_try_advance_pipeline()` | 推进 Step 后 | `await _broadcast_pipeline_update(...)` |
| `_handle_hash_stop()` | 停止后 | `await _broadcast_pipeline_update(...)` |
| `_auto_dispatch()` | 派活后 | `await _broadcast_pipeline_update(...)` |

### 4.4 无需改动的文件

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | Schema 和数据已完整，R112 只读不写 |
| `handler.py` | 管线逻辑不涉及 `!` 命令 |
| `commands/pipeline.py` | 不修改命令处理器 |
| `pipeline_auto_starter.py` | 废弃，不碰 |
| `Dockerfile` | 纯 Web 前端改动，无需重启容器结构 |
| `shared/protocol.py` | 不涉及协议变更 |

---

## 五、验收标准

### 5.1 API 端点

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 1 | `GET /api/pipelines` 返回当前所有管线 | curl 访问端点，确认含活跃 + 已完成管线 |
| 2 | `GET /api/pipelines/R112` 返回单管线完整数据 | curl 确认字段完整（steps/references/status） |
| 3 | 无管线时返回空列表 `{"pipelines": []}` | `##stop##all` 清理后验证 |
| 4 | 不存在的轮次返回 404 | `GET /api/pipelines/NONEXIST` → 404 |

### 5.2 Web 端管线 Tab

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 5 | Tab 栏出现「📊 管线」Tab | 浏览器打开 Web 端，确认 Tab 可见 |
| 6 | 活跃管线卡片展示进度条和 Step 状态 | `##start##R112` 后刷新页面，确认卡片出现 |
| 7 | 每步显示正确的状态图标（✅🟢⬜） | 对比 pipeline_contexts.json 实际数据 |
| 8 | 已完成 Step 显示产出链接 | 点链接确认跳转正确 |
| 9 | `##status##R112` 命令行 + Web 端状态一致 | 两者对比 |

### 5.3 WebSocket 实时更新

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 10 | `##start##R112` 后 Web 端自动出现新卡片 | 不刷新页面，观察 3s 内卡片出现 |
| 11 | Step 推进后 Web 端状态自动变化 | 小谷回复 "已完成 ✅ R112 Step 1" → Web 端 Step 1 变 ✅ |
| 12 | `##stop##R112` 后卡片状态变为 🛑 CANCELLED | 不刷新页面观察状态变化 |

### 5.4 兼容性

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 13 | 桌面端网格排列正常（≥2 列） | 1920px 窗口验证 |
| 14 | 移动端单列堆叠正常 | 375px 窗口验证 |
| 15 | WebSocket 断连重连后管线数据不丢失 | 刷新页面后卡片仍存在 |

---

## 六、不改的内容

| 事项 | 原因 |
|:-----|:------|
| ❌ 管线状态管理逻辑改动 | `PipelineContextManager` / `_try_advance_pipeline` 不动 |
| ❌ `!` 命令体系修改 | 不涉及 handler.py |
| ❌ 添加新的 Step 或角色 | 已有 6 步 6 角色不变 |
| ❌ Telegram Bot 交互 | 纯 Web 端改动，不涉及 TG |
| ❌ API Key / RBAC 权限体系 | 后续轮次再做 |
| ❌ 历史管线数据的迁移 | 只读当前 `pipeline_contexts.json` |
| ❌ Phase 3 Coder Agent | 不是本轮范围 |

---

## 七、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — Web 端管线进度可视化 |

---

> **审核前确认清单：**
> - [x] 方向确认：Web 端管线仪表盘
> - [ ] 项目负责人审核：✅ 通过 ❌ 驳回
> - [ ] 审核签字：__________
