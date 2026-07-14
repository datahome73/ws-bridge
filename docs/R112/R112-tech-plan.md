# R112 — Web 端管线进度可视化 技术方案

> **版本：** v1.0
> **日期：** 2026-07-14
> **状态：** 📝 技术方案
> **轮次：** R112
> **架构师：** 小开

---

## 一、架构概要

```
┌──────────────────────┐    DATA_DIR 共享    ┌──────────────────────┐
│  ws_server (WSS 8765) │  ────────────────→  │  web_ui (HTTP 8766)  │
│  pipeline_contexts.json│  (同一容器,同FS)    │  读取 JSON → API    │
│  PipelineContextManager│                     │  → Web 前端渲染      │
└──────────────────────┘                     └──────────────────────┘
```

**核心决策：** Web UI 进程直接读 `pipeline_contexts.json`（通过 `PipelineContextManager`），不走 WS 进程 RPC。两进程共享 `DATA_DIR`（已验证 ✅）。

---

## 二、API 数据源方案

### 方案：直接使用 PipelineContextManager

Web UI 侧引用 `PipelineContextManager` 读取数据：

```python
from server.ws_server.pipeline_context import PipelineContextManager

mgr = PipelineContextManager(data_dir=DATA_DIR)
pipelines = mgr.get_all_active()
for p in pipelines:
    d = p.to_dict()  # 已序列化，直接可用
```

**理由：**
- `DATA_DIR` 两进程共享，Manager 直接读同一份 `pipeline_contexts.json`
- `to_dict()` 已输出所有前端所需字段 ✅
- 不需要额外建 API 数据模型，零改动 `pipeline_context.py` ✅

| 方式 | 复杂度 | 一致性 | 选型 |
|:-----|:------:|:------:|:----:|
| 直接读 JSON 文件 | 低 | 弱（无锁） | ❌ |
| PipelineContextManager | 低 | 强（带锁持久化） | ✅ |
| WS RPC 查询 | 高 | 强 | ❌ |

---

## 三、API 端点设计

在 `viewer.py` 新增两个 aiohttp handler：

### 3.1 `GET /api/pipelines` — 管线列表

```python
@routes.get("/api/pipelines")
async def handle_pipelines_list(request):
    mgr = PipelineContextManager(data_dir=DATA_DIR)
    items = []
    for ctx in mgr.get_all_active():
        d = ctx.to_dict()
        items.append({
            "round_name": d["round_name"],
            "round_title": d.get("round_title", d["round_name"]),
            "status": d["status"],
            "current_step": d["current_step"],
            "total_steps": d["total_steps"],
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
            "steps": _summarize_steps(d.get("steps", [])),
            "references": d.get("references", {}),
        })
    # 同时加载已完成/已归档管线
    return web.json_response({"pipelines": items})
```

**`_summarize_steps()` 辅助函数：** 从 StepInfo 列表提取前端展示字段：

```python
def _summarize_steps(steps: list) -> list:
    result = []
    for s in steps:
        if isinstance(s, dict):
            result.append({
                "step_key": s.get("step_key", ""),
                "role": s.get("role", ""),
                "title": s.get("title", ""),
                "status": s.get("status", "pending"),
                "agent_name": s.get("agent_name", ""),
                "result_msg": s.get("result_msg", ""),
                "output": s.get("output"),
            })
    return result
```

### 3.2 `GET /api/pipelines/{round_name}` — 单管线详情

```python
@routes.get("/api/pipelines/{round_name}")
async def handle_pipeline_detail(request):
    mgr = PipelineContextManager(data_dir=DATA_DIR)
    ctx = mgr.get(round_name)
    if not ctx:
        # 回退：检查已归档的 history JSONL
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(ctx.to_dict())
```

### 3.3 惰性初始化模式

因 `PipelineContextManager` 构造时读磁盘，每次请求新建有轻微开销。采用 **进程级单例**：

```python
_PIPELINE_MGR = None

def _get_pipeline_mgr() -> PipelineContextManager:
    global _PIPELINE_MGR
    if _PIPELINE_MGR is None:
        _PIPELINE_MGR = PipelineContextManager(data_dir=DATA_DIR)
    return _PIPELINE_MGR
```

---

## 四、前端渲染方案

### 策略：纯内嵌 templates.py（沿用现有模式）

- 新增第 4 个 Tab「📊 管线」，在 `TAB_STATE` 中追加
- HTML/CSS/JS 全部内联在 `CHAT_TEMPLATE` 中（~150 行）
- 理由：R109 已确定 Web 端保持内嵌，不拆独立文件 ✅

### 4.1 Tab 注册

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__',    label: '📬 收件箱',   permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史',    permanent: true, visible: true },
  tab4: { id: 'tab4', channel: null,           label: '📊 管线',    permanent: true, visible: true },
};
```

### 4.2 管线列表渲染

`selectTab('tab4')` 时触发：

```javascript
if (tabId === 'tab4') {
  document.getElementById('inputArea').style.display = 'none';
  renderPipelineDashboard();
}
```

`renderPipelineDashboard()` 功能：

| 元素 | 实现 |
|:-----|:------|
| 管线卡片列表 | 每管线一个卡片，含 round_name + 状态标签 + 进度条 |
| 进度条 | CSS 纯色背景，`width: ${(current_step-1)/total_steps*100}%` |
| Step 行 | 每步一行：状态图标 + 角色名 + Agent 名 + 产出链接 |
| 状态图标 | 🟢 完成 / 🟡 执行中 / ⬜ 待派活 / 🔴 失败 / ⏸️ 已跳过 |
| 刷新频率 | 每 15s 轮询 `/api/pipelines` |

### 4.3 管线卡片 HTML 结构

```html
<div class="pipeline-card">
  <div class="pipeline-header">
    <span class="pipeline-round">R112</span>
    <span class="pipeline-status status-running">🟢 运行中</span>
    <span class="pipeline-time">更新: 14:32</span>
  </div>
  <div class="pipeline-progress">
    <div class="progress-bar">
      <div class="progress-fill" style="width:33%"></div>
    </div>
    <span class="progress-text">3/6 步</span>
  </div>
  <div class="pipeline-step-list">
    <!-- 每步 -->
    <div class="step-row step-done">
      <span class="step-icon">🟢</span>
      <span class="step-role">PM</span>
      <span class="step-agent">小谷</span>
      <span class="step-output">📄 已审核</span>
    </div>
    <div class="step-row step-active">
      <span class="step-icon">🟡</span>
      <span class="step-role">Arch</span>
      <span class="step-agent">小开</span>
      <span class="step-output">⏳ 执行中...</span>
    </div>
    <div class="step-row step-pending">
      <span class="step-icon">⬜</span>
      <span class="step-role">Dev</span>
      <span class="step-agent">爱泰</span>
      <span class="step-output"></span>
    </div>
  </div>
</div>
```

### 4.4 状态颜色映射

| Status | Icon | CSS class |
|:-------|:----:|:----------|
| done | 🟢 | `step-done` |
| active | 🟡 | `step-active` |
| pending | ⬜ | `step-pending` |
| failed | 🔴 | `step-failed` |
| skipped | ⏸️ | `step-skipped` |

---

## 五、轮询策略（沿用现有机制）

### 当前轮询格局

| 轮询 | 间隔 | 现有 | R112 变化 |
|:-----|:----:|:----:|:---------:|
| 消息拉取 | 5s | ✅ | 不变 |
| 工作室列表 | 15s | ✅ | 不变 |
| Bot 状态 | 15s | ✅ | 不变 |
| **管线数据** | **15s** | ❌ | **新增** |

### 不使用 WebSocket 推送的理由

- 前端已全量使用 HTTP 轮询（R101 重构后的设计）
- 管线数据更新频率低（几分钟一次），15s 轮询足够
- 无需引入 WS 推送通道，保持架构简单
- 前后端解耦：WS 进程 crash 不影响 Web UI 展示历史数据

---

## 六、样式设计

沿用现有暗色主题（`#0d1117` 背景 + `#161b22` 卡片），新增管线专用样式：

| 样式 | 值 |
|:-----|:----|
| 卡片背景 | `#161b22` |
| 卡片边框 | `1px solid #30363d` |
| 进度条底色 | `#30363d` |
| 进度条填充 | `#4fc3f7`（蓝色渐变） |
| Step 完成行 | 左侧绿色边框 `3px solid #3fb950` |
| Step 执行中行 | 左侧黄色边框 `3px solid #ffd700` |
| Step 待派活行 | 左侧灰色边框 `3px solid #30363d` |
| 管线标题字色 | `#c9d1d9` |
| 状态标签字色 | 按状态映射 |

---

## 七、改动清单

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/web_ui/viewer.py` | 新增 `handle_pipelines_list`, `handle_pipeline_detail`, `_summarize_steps`, `_get_pipeline_mgr` | ~40 行 |
| `server/web_ui/templates.py` | 新增 Tab4、`renderPipelineDashboard()`、管线 CSS/JS | ~150 行 |

**零改动文件（已验证 ✅）：**

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | 复用 `to_dict()` / `get_all_active()` / `get()` |
| `server/ws_server/main.py` | 管线逻辑不变 |
| `command_utils.py` / `commands/pipeline.py` | 不涉及 |
| `pipeline_auto_starter.py` | 废弃，不碰 |
| `config.py` / `state.py` | 无需新增配置 |

---

## 八、验收标准

| # | 验收项 | 方法 |
|:-:|:-------|:-----|
| 1 | 打开 Web 端看到「📊 管线」Tab | 浏览器访问 | 
| 2 | Tab 显示所有活跃管线卡片 | 有管线时显示卡片，无管线时显示「暂无活跃管线」|
| 3 | 每卡片正确显示进度条 | 进度条百分比与 `current_step/total_steps` 一致 |
| 4 | Step 行正确显示角色 + Agent 名 + 状态图标 | 与 `pipeline_contexts.json` 数据一致 |
| 5 | 已完成 Step 显示产出链接（SHA/references） | 如果 `output.sha` 存在则显示 |
| 6 | 15s 轮询刷新 | 修改 JSON 文件后 15s 内 Web 端更新 |
| 7 | 无管线时不报错，显示空状态提示 | 清理 `pipeline_contexts.json` 后刷新 |
| 8 | 不破坏现有 3-Tab 功能 | 收件箱 / 管理员 / 历史 均正常工作 |
| 9 | 单管线详情 API 返回完整数据 | `GET /api/pipelines/R112` |

---

## 九、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — Web 端管线进度可视化技术方案 |
