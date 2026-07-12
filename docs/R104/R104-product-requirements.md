# R104: Web 服务增加工作区列表 API — 解决前端加载失败问题

> **版本：** v1.0
> **日期：** 2026-07-13
> **状态：** 📝 需求文档
> **轮次：** R104

---

## 一、背景

R101 WSS/Web 解耦后，ws-bridge 拆分为两个独立进程：

| 服务 | 端口 | 路由 | nginx 代理 |
|:-----|:----:|:-----|:----------:|
| **WSS 核心** | 8765 | `/api/workspaces`, `/api/status`, `/ws` | ❌ |
| **Web 服务** | 8766 | `/chat`, `/api/chat/**`, `/api/bot_status`, etc. | ✅ |

**问题：** Web 前端 JS 中 `renderWsPanel()` 调用 `fetch('/api/workspaces')`，但该端点只注册在 WSS 核心（8765），Web 服务（8766）没有此路由。nginx 只代理 8766 端口，`/api/workspaces` 返回 404 → 工作区面板加载失败。

同样，`/api/chat/archive` 依赖 `_archive_state.json`，只覆盖已关闭的工作区，不能用于查看全部工作区。

## 二、需求

### 2.1 Web 服务新增 `/api/workspaces` 端点

**目标：** Web 前端的工作区面板能正常加载工作区列表。

**实现方式：** 在 `web_viewer.py` 中新增 `handle_api_workspaces()` 处理函数，直接从共享 `DATA_DIR` 读取 `workspaces.json` 文件序列化数据，返回给前端。

与 WSS 核心的 `workspace_api.py` 的 `api_workspaces()` 返回格式保持一致：

```json
{
  "workspaces": [
    {
      "id": "ws_xxx",
      "name": "R102 dev workspace",
      "owner_name": "小谷",
      "state": "active",
      "member_count": 3,
      "created_at": 1783749200.0,
      "last_active_at": 1783836186.0,
      "closed_at": null,
      "pipeline_round": "R102",
      "roles": ["pm", "arch", "dev"]
    }
  ],
  "count": 1
}
```

**读取方式：** 直接调用 `workspace.get_all_workspaces()`（Web 服务在启动时已通过 `persistence.load_*` 加载了数据目录，workspace 模块可共用）。

### 2.2 不需要改动的

| 项目 | 原因 |
|:-----|:------|
| WSS 核心（`__main__.py` / `workspace_api.py`） | 原有端点保留，互相独立 |
| 前端 JS 逻辑（`templates.py`） | JS 已经用 `fetch('/api/workspaces')` 调用了，加后端即可 |
| nginx 配置 | 不需要改——Web 服务端口 8766 已有 nginx 代理 |
| WebSocket / 消息路由 | 纯 HTTP API 增强 |

### 2.3 前后端调用链路

```
浏览器 JS: fetch('/api/workspaces')
  → nginx (443) → proxy_pass → Web 服务 (8766) 
  → handle_api_workspaces()
  → workspace.get_all_workspaces()          # 读 workspaces.json
  → 返回 JSON 给前端
  → renderWsPanel() 渲染面板
```

## 三、验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `GET /api/workspaces` 返回工作区列表 | `curl https://wsim.datahome73.cloud/api/workspaces` 返回 200 + JSON |
| 2 | 返回格式包含 `workspaces` 和 `count` 字段 | 同上，检查 JSON 结构 |
| 3 | 每个工作区包含 `pipeline_round` 和 `roles` 字段 | 检查字段存在 |
| 4 | Web 前端工作区面板正常加载 | 登录 Web 端→点击「📋 历史工作室」→列表出现 |
| 5 | 点击活跃工作区→切换到历史 Tab 查看消息 | 点击工作区→显示消息列表（非「加载失败」） |
| 6 | 无权限访问时返回 401 | 无 token 请求时返回 `{"error": "unauthorized"}` |
| 7 | WSS 核心原有端点不受影响 | `curl http://127.0.0.1:8765/api/workspaces` 仍正常 |

## 四、变更文件清单

| 文件 | 改动类型 | 估算行数 |
|:-----|:---------|:---------|
| `server/web_viewer.py` | 新增 `handle_api_workspaces()` + 注册路由 | +15 行 |
| `server/web_service.py` | 无需改动（已有 `web_viewer.setup_routes`） | 0 行 |

**总估算：约 +15 行**

## 五、风险与注意事项

| 风险 | 等级 | 缓解 |
|:-----|:-----|:------|
| workspace 模块在 Web 服务中导入可能缺初始化 | 🟡 | Web 服务启动时已 `persistence.load_*()` 初始化 DATA_DIR，workspace 模块使用相同的 `DATA_DIR` 常量 |
| 返回数据与 WSS 核心版本不一致 | 🟢 | 共用 `workspace.get_all_workspaces()`，数据源相同 |
| 前端的 tab3 切换逻辑依赖 `loadArchiveMessages`（只对已归档工作区有效） | 🟡 | 本次先加 `/api/workspaces` 修复面板加载；archive 加载问题留到 R105 或顺带修 |
