# R112 Step 2 — Web 端管线进度可视化技术方案

> **轮次：** R112
> **版本：** v1.0
> **日期：** 2026-07-15
> **设计角色：** 小开（架构师）
> **实现角色：** 爱泰（开发工程师）
>
> **需求文档：** [R112-product-requirements.md](R112-product-requirements.md)
> **审核：** [R112 审核通过](https://github.com/datahome73/ws-bridge/blob/main/docs/R112/WORK_PLAN.md)

---

## 一、架构总览

```
WS Server (port 8765)                 Web HTTP Service (port 8766)
┌────────────────────────┐           ┌──────────────────────────────┐
│  PipelineContextManager │  writes   │                              │
│  _save() → JSON        │──────────→│  READ: DATA_DIR /            │
│                        │  shared   │    pipeline_contexts.json    │
│  _append_history()     │  DATA_DIR │    pipeline_contexts_hist.   │
│  → JSONL               │──────────→│                              │
└────────────────────────┘           │  viewer.py API handlers      │
                                     │    GET /api/pipelines        │
                                     │    GET /api/pipelines/{name} │
                                     │                              │
                                     │  templates.py frontend       │
                                     │    📊 管线 Tab (内联 JS)     │
                                     │    5s HTTP polling           │
                                     └──────────────────────────────┘
```

**关键约束：**
- Web HTTP Service 与 WS Server 是**独立进程**，共享 `DATA_DIR`（`config.DATA_DIR`）
- `PipelineContextManager` 在每次突变后写 `DATA_DIR/pipeline_contexts.json`（同步持久化）
- Web 端当前使用 **5s HTTP 轮询** 模式（R101 迁移决定），管线 Tab 沿用同一模式
- **管线逻辑零改动** — Web 端只读不写管线数据

---

## 二、设计决策

### 2.1 数据源方案 ✅ 直接读 JSON 文件

| 方案 | 评价 |
|:-----|:------|
| ❌ HTTP relay 到 WS Server API | 增加一个进程间 HTTP 依赖和延迟 |
| ❌ 跨进程 PipelineContextManager 调用 | 不同内存空间，不可行 |
| **✅ 直接读 `DATA_DIR/pipeline_contexts.json`** | 简单可靠，Manager 每次突变同步持久化 |

**活跃管线** — 读 `DATA_DIR/pipeline_contexts.json`（Manager 的 `_save()` 同步写，无延迟竞争）。
**已归档管线** — 读 `DATA_DIR/pipeline_contexts_history.jsonl`（JSONL 格式，逐行 JSON）。

**读取函数（`viewer.py` 中新增）：**

```python
_PIPELINE_FILE = "pipeline_contexts.json"
_PIPELINE_HISTORY_FILE = "pipeline_contexts_history.jsonl"

def _load_pipelines() -> dict:
    """从 JSON 文件加载所有管线（活跃 + 归档）。"""
    active = {}
    path = config.DATA_DIR / _PIPELINE_FILE
    if path.exists():
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # 从 JSONL 读归档（最近 50 条）
    hist_path = config.DATA_DIR / _PIPELINE_HISTORY_FILE
    archived = []
    if hist_path.exists():
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        archived.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
    return {"active": active, "archived": archived[-50:]}
```

### 2.2 WebSocket 方案 ✅ 不新增 — 用现有 5s HTTP 轮询

| 方案 | 评价 |
|:-----|:------|
| ❌ WebSocket 推送 | 需新增 WS 连接 + 协议 + 断连重连，管线变更频率低（几分钟一次） |
| **✅ 5s HTTP 轮询（复用现有 `pollActiveChannel` 模式）** | 零新增连接，管线变更在 5s 内可见，足够实时 |

**轮询流程沿用当前 chat 模式：**

```
setInterval(async function() {
    const resp = await fetch('/api/pipelines?token=' + TOKEN);
    const data = await resp.json();
    if (JSON.stringify(data) !== lastPipelineJson) {
        lastPipelineJson = JSON.stringify(data);
        renderPipelineDashboard(data);
    }
}, 5000);
```

### 2.3 前端渲染方案 ✅ 内嵌 `templates.py`

| 方案 | 评价 |
|:-----|:------|
| ❌ 独立前端文件 | 需修改 Dockerfile / 部署流程 |
| **✅ templates.py 内联（当前模式）** | 全部在 CHAT_TEMPLATE 字符串中，零部署改动 |

**新增内容（~150 行）：**
- **HTML** — 新 Tab 面板容器（`<div id="pipelinePanel">`），与现有 `#tabBar`、`#msgList` 同级
- **CSS** — 管线卡片、进度条、Step 徽章、响应式布局
- **JS** — `TAB_STATE` 增加 `tab4` 条目、`renderPipelineDashboard()`、5s 轮询

### 2.4 字段序列化 ✅ 直接复用 `to_dict()`

`PipelineContext.to_dict()` 已输出所有前端需要字段：

| JSON 字段 | 前端用途 | 说明 |
|:----------|:---------|:------|
| `round_name` | 管线标题 | ✅ |
| `round_title` | 管线副标题 | ✅ |
| `status` | 状态标签 + 卡片配色 | `RUNNING` 🟢 / `COMPLETED` 🔵 / `CANCELLED` 🔴 |
| `current_step` | 进度条填充 | ✅ |
| `total_steps` | 进度条分母 | 默认 6 |
| `steps[].step_key` | Step 序号 | ✅ |
| `steps[].role` | 角色标识 | ✅ |
| `steps[].agent_name` | Agent 名称 | ✅ |
| `steps[].status` | 状态图标 | `pending`⬜/`active`🟢/`done`✅/`failed`❌/`skipped`⏭ |
| `steps[].result_msg` | 产出链接 | 如 `✅ 完成，已推 dev: xxxx` |
| `steps[].output` | 产出详情 | SHA/URL 等字典 |
| `references` | 文档链接 | URL 列表 |
| `created_at` | 创建时间 | ✅ |
| `updated_at` | 最后更新 | ✅ |
| `created_by` | 发起者 | ✅ |

---

## 三、Tab 模型扩展

### 3.1 `TAB_STATE` 增加 tab4

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__',    label: '📬 收件箱',   permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史',    permanent: true, visible: true },
  tab4: { id: 'tab4', channel: null,           label: '📊 管线',    permanent: true, visible: true },
};
```

### 3.2 `renderTabBar()` 增加 tab4 渲染

在 `tab3` 渲染分支后添加 `tab4` 分支：

```javascript
// In renderTabBar():
} else if (id === 'tab4') {
  html += '<div class="tab' + (isActive ? ' active' : '') + '" data-tab="tab4" onclick="selectTab(\'tab4\')">📊 管线</div>';
}
```

### 3.3 `selectTab()` routing

已有 `selectTab()` 的 msgList 显示/隐藏切换逻辑。tab4 应：
- 隐藏 `#msgList`（消息列表）
- 显示 `#pipelinePanel`（管线仪表盘）
- 触发 `pollPipelineData()` 首次加载

```javascript
// In selectTab():
if (tabId === 'tab4') {
  document.getElementById('msgList').style.display = 'none';
  document.getElementById('pipelinePanel').style.display = 'block';
  pollPipelineData(); // 立即加载
} else {
  document.getElementById('msgList').style.display = 'block';
  document.getElementById('pipelinePanel').style.display = 'none';
}
```

---

## 四、API 端点

### 4.1 `GET /api/pipelines`

**位于 `viewer.py`**，返回所有管线数据。

```python
async def handle_api_pipelines(request: web.Request) -> web.Response:
    """返回所有管线数据（活跃 + 已归档）"""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    data = _load_pipelines()
    return web.json_response(data)
```

### 4.2 `GET /api/pipelines/{round_name}`

```python
async def handle_api_pipeline_detail(request: web.Request) -> web.Response:
    """返回单条管线完整详情"""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    round_name = request.match_info.get("round_name", "")
    data = _load_pipelines()
    # 查活跃
    if round_name in data.get("active", {}):
        return web.json_response(data["active"][round_name])
    # 查归档
    for item in data.get("archived", []):
        if item.get("round_name") == round_name:
            return web.json_response(item)
    return web.json_response({"error": "not found"}, status=404)
```

### 4.3 路由注册

```python
# In setup_routes():
app.router.add_get("/api/pipelines", handle_api_pipelines)
app.router.add_get("/api/pipelines/{round_name}", handle_api_pipeline_detail)
```

---

## 五、前端渲染设计

### 5.1 HTML 面板容器

```html
<div id="pipelinePanel" style="display:none;padding:16px;max-width:900px;margin:0 auto;">
  <div id="pipelineDashboard"></div>
</div>
```

### 5.2 CSS 样式

```css
/* 管线卡片 */
.pipeline-card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:16px; }
.pipeline-card.running { border-left:4px solid #3fb950; }
.pipeline-card.completed { border-left:4px solid #58a6ff; }
.pipeline-card.cancelled { border-left:4px solid #f85149; }

/* 进度条 */
.progress-bar { height:8px; background:#21262d; border-radius:4px; margin:8px 0; }
.progress-fill { height:100%; border-radius:4px; transition:width 0.3s ease; }
.progress-fill.running { background:linear-gradient(90deg,#3fb950,#2ea043); }
.progress-fill.completed { background:#58a6ff; }

/* Step 行 */
.step-row { display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #21262d; }
.step-row:last-child { border-bottom:none; }
.step-icon { font-size:1.1rem; width:24px; text-align:center; }
.step-agent { color:#58a6ff; font-weight:500; font-size:0.85rem; min-width:48px; }
.step-title { color:#c9d1d9; font-size:0.85rem; flex:1; }
.step-result { color:#8b949e; font-size:0.8rem; }
.step-result a { color:#58a6ff; text-decoration:none; }
.step-result a:hover { text-decoration:underline; }

/* 响应式 */
@media (max-width:768px) {
  .pipeline-grid { grid-template-columns:1fr; }
}
@media (min-width:769px) {
  .pipeline-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
}
```

### 5.3 JS 渲染函数

```javascript
let lastPipelineJson = '';

async function pollPipelineData() {
  try {
    const resp = await fetch('/api/pipelines?token=' + encodeURIComponent(TOKEN));
    if (!resp.ok) return;
    const data = await resp.json();
    const json = JSON.stringify(data);
    if (json === lastPipelineJson) return;
    lastPipelineJson = json;
    renderPipelineDashboard(data);
  } catch(_) {}
}

function renderPipelineDashboard(data) {
  const container = document.getElementById('pipelineDashboard');
  const active = data.active || {};
  const archived = data.archived || [];
  
  let html = '<h3 style="margin-bottom:16px;">📊 管线仪表盘</h3>';
  
  // 活跃管线
  const activeKeys = Object.keys(active);
  if (activeKeys.length > 0) {
    html += '<div class="pipeline-grid">';
    for (const key of activeKeys) {
      html += buildPipelineCard(active[key]);
    }
    html += '</div>';
  }
  
  // 已归档（最近5条，折叠）
  // ...
  
  container.innerHTML = html;
}

function buildPipelineCard(ctx) {
  const status = ctx.status || 'RUNNING';
  const pct = ((ctx.current_step - 1) / ctx.total_steps * 100).toFixed(0);
  const steps = ctx.steps || [];
  const statusIcons = {done:'✅',active:'🟢',pending:'⬜',failed:'❌',skipped:'⏭'};
  
  let html = '<div class="pipeline-card ' + status.toLowerCase() + '">';
  html += '<div style="display:flex;justify-content:space-between;margin-bottom:4px;">';
  html += '<strong>' + (ctx.round_title || ctx.round_name) + '</strong>';
  html += '<span>' + statusIconFor(status) + ' ' + status + '</span></div>';
  html += '<div style="font-size:0.8rem;color:#8b949e;margin-bottom:4px;">';
  html += 'Step ' + ctx.current_step + '/' + ctx.total_steps;
  html += ' · ' + formatTime(ctx.updated_at || ctx.created_at) + '更新';
  html += '</div>';
  html += '<div class="progress-bar"><div class="progress-fill ' + status.toLowerCase() + '" style="width:' + pct + '%;"></div></div>';
  
  for (const s of steps) {
    const icon = statusIcons[s.status] || '⬜';
    html += '<div class="step-row">';
    html += '<span class="step-icon">' + icon + '</span>';
    html += '<span class="step-agent">' + escapeHtml(s.agent_name || s.role || '?') + '</span>';
    html += '<span class="step-title">' + escapeHtml(s.title || s.step_key || '') + '</span>';
    if (s.result_msg) {
      html += '<span class="step-result">' + escapeHtml(s.result_msg) + '</span>';
    }
    html += '</div>';
  }
  
  html += '</div>';
  return html;
}

function statusIconFor(status) {
  return {RUNNING:'🟢',COMPLETED:'✅',CANCELLED:'🛑',BLOCKED:'🔴',INIT:'⚪'}[status] || '⚪';
}
```

---

## 六、改动清单

### 6.1 `server/web_ui/templates.py` — CHAT_TEMPLATE 内新增

| 项目 | 位置 | 行数 |
|:-----|:------|:-----|
| `<div id="pipelinePanel">` HTML 容器 | 末尾 `</script>` 之前 | ~5 行 |
| CSS 管线卡片样式 | 现有 `<style>` 块末尾 | ~30 行 |
| `TAB_STATE.tab4` 条目 | JS 开头 L134-139 | 1 行 |
| `renderTabBar()` tab4 分支 | 渲染 tab3 后 | ~5 行 |
| `selectTab()` tab4 分支 | msgList 显示/隐藏逻辑 | ~8 行 |
| `pollPipelineData()` / `renderPipelineDashboard()` / `buildPipelineCard()` | 末尾 `init()` 之前 | ~80 行 |
| `init()` 中启动 tab4 轮询 | `setInterval` 段落 | ~15 行 |

**合计：~150 行内嵌到 CHAT_TEMPLATE 中。**

### 6.2 `server/web_ui/viewer.py` — API 端点

| 项目 | 位置 | 行数 |
|:-----|:------|:-----|
| `_load_pipelines()` 辅助函数 | 文件开头，`_load_json` 之后 | ~20 行 |
| `handle_api_pipelines()` | API handlers 区域 | ~8 行 |
| `handle_api_pipeline_detail()` | API handlers 区域 | ~15 行 |
| `setup_routes()` 中注册 | `app.router.add_get(...)` | 2 行 |

**合计：~45 行 Python。**

### 6.3 零改动文件

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | 数据 Schema 和 `to_dict()` 已完整，只读不写 |
| `main.py` (WS Server) | 不需要 WebSocket 推送，5s 轮询自读文件 |
| `command_utils.py` | 无广播需求 |
| `commands/pipeline.py` | 不修改命令处理器 |
| `pipeline_auto_starter.py` | 废弃，不碰 |
| `config.py` | 无需新增配置项 |
| `Dockerfile` | 纯内联改动 |
| `shared/protocol.py` | 不涉及协议变更 |

---

## 七、数据一致性保证

| 场景 | 保证 |
|:-----|:------|
| PipelineContextManager 写 `pipeline_contexts.json` | 同步写（`_save()`），写后立即落盘 |
| Web 端 5s 轮询读取 | 与 Manager 写操作无竞态（读已落盘数据） |
| 归档管线追加 JSONL | `_append_history()` 同步追加，且 archive() 有锁 |
| WS Server 重启 | Manager 从 JSON 恢复（`_load()`），数据不丢 |
| Web 端首次加载 vs 轮询 | 首次是完整拉取，后续 diff 增量渲染 |

---

## 八、验收标准（对应 PRD §5）

| # | 验收项 | 验证方法 | 通过条件 |
|:-:|:-------|:---------|:---------|
| 1 | `GET /api/pipelines` 返回 JSON | `curl /api/pipelines?token=...` | 含 `active` + `archived` 字段 |
| 2 | 无管线时返回空对象 | 清理后 curl | `{"active":{}, "archived":[]}` |
| 3 | Tab 栏出现「📊 管线」Tab | 浏览器查看 | Tab 可见，排在历史之后 |
| 4 | 活跃管线卡片展示进度条 + Step | `##start##R112-test` 后刷新 | 卡片显示每步状态 |
| 5 | 状态图标正确 | 比对 JSON | ✅🟢⬜❌⏭ 与 JSON 一致 |
| 6 | 已完成 Step 显示 `result_msg` | 有已完成管线 | 行末显示文本 |
| 7 | `##stop##R112-test` 后 🛑 显示 | 停止后轮询 | 卡片变红色边框 |
| 8 | 桌面端 2 列网格 | 1920px | `.pipeline-grid` grid-template-columns: 1fr 1fr |
| 9 | 移动端 1 列 | 375px | `.pipeline-grid` → 1fr |
| 10 | 刷新后数据不丢 | 刷新页面 | 卡片仍在 |

---

## 九、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-15 | 初稿 |
