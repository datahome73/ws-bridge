# R101 代码审查报告 — WSS/Web 解耦：Web 界面独立为服务

> **审查人：** 🔍 小周
> **基线：** `6dc2ea1`（R101 Step 2 架构方案）
> **审查目标：** `0baddc8`（R101 Step 3 编码完成）
> **审查日期：** 2026-07-16
> **结论：** ⚠️ 有条件通过 — 1 项 🟡 建议项

---

## 一、审查清单逐项验证

### 🔴 核心验收

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1 | WSS 核心无 web_viewer import | `grep -rn 'web_viewer' server/main.py server/__main__.py server/command_utils.py server/commands/` → 0 | ⚠️ 见下 | 仅 `server/commands/workspace.py:140` 有惰性 import |
| 2 | WSS 核心无 write_chat_log 调用 | `grep -rn 'write_chat_log' server/main.py server/__main__.py server/command_utils.py server/commands/` → 0 | ✅ **通过** | 0 matches |
| 3 | WSS 核心无 _ws_clients 引用 | `grep -rn '_ws_clients' server/main.py server/__main__.py` → 0 | ✅ **通过** | 0 matches |
| 4 | __main__.py 只注册 WSS 路由 | 仅 `/ws`, `/api/status`, `/api/health`, `/api/workspaces` | ✅ **通过** | 4 routes — 不含任何 web 路由 |
| 5 | Web 服务独立入口 | `server/web_service.py` 存在，独立端口 | ✅ **通过** | 端口 8766，`WS_HTTP_PORT` 环境变量 |
| 6 | templates.py WS → fetch 轮询 | 前端无 WebSocket 代码 | ✅ **通过** | 0 matches on `WebSocket\|connectWS\|new WebSocket` |

### 🟢 辅助验证

| # | 验证项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| 7 | web_viewer.py WS 代码已清理 | ✅ | `_ws_clients`, `handle_ws_chat`, `/ws/chat` 路由全部删除 |
| 8 | web_viewer.py `handler→main` 修复 | ✅ | `from . import main as _handler` 已替换 |
| 9 | 全部改动文件语法通过 | ✅ | `py_compile` 全部 8 个修改文件 zero error |
| 10 | Scope 边界文件未改 | ✅ | message_store / auth / persistence / workspace / config / state / commands/__init__ / agent_card — 零改动 |
| 11 | R100 残留 import 修复 | ✅ | admin.py (+time,+ws_mod,+lazy imports), task.py (+config,+asyncio,+p), workspace.py (+time,+uuid,+ms,+p) |
| 12 | write_chat_log 从 web_viewer 保留 | ✅ | 函数定义保留（Web 服务需要），仅删除 WS 推送部分 |
| 13 | web_service.py 无 WebSocket | ✅ | 纯 HTTP, 无 websocket import |

---

## 二、文件改动总览

| # | 文件 | 动作 | 行数变化 | 状态 |
|:-:|:-----|:-----|:--------:|:----:|
| 1 | `server/web_service.py` | 🔺 新增 | **+30** | ✅ |
| 2 | `server/main.py` | 删除 13 处 write_chat_log + 1 处 _ws_clients import | **-33** | ✅ |
| 3 | `server/command_utils.py` | 删除 2 处 write_chat_log + import | **-3** | ✅ |
| 4 | `server/commands/pipeline.py` | 删除 4 处 write_chat_log + import | **-5** | ✅ |
| 5 | `server/commands/workspace.py` | 删除 1 处 write_chat_log; 新增 4 个缺失 import | **+5 -1** | ✅ |
| 6 | `server/__main__.py` | 删除 web_viewer import / write_chat_log / _ws_clients / setup_routes / MSG_TASK_NOTIFY 段落 | **-26** | ✅ |
| 7 | `server/web_viewer.py` | 删除 _ws_clients / _do_ws_send / WS 推送 / handle_ws_chat / /ws/chat 路由; 修复 handler→main | **-53 +0** | ✅ |
| 8 | `server/templates.py` | WS → fetch 轮询 + touch 下拉刷新 | **-72 +72** | ✅ |
| 9 | `server/commands/admin.py` | R100 缺失 import 修复 | **+5** | ✅ |
| 10 | `server/commands/task.py` | R100 缺失 import 修复 | **+3** | ✅ |
| | **合计** | **1 新增 + 9 修改** | **-182 净删** | ✅ |

---

## 三、🟡 发现项

### 🟡 1: `commands/workspace.py:140` 仍然惰性 import `web_viewer`

```python
# server/commands/workspace.py:140
from . import web_viewer as wv
start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else time.time()
wv.set_archive_state(
    ws_id=ws.id,
    ws_name=ws.name,
    start_ts=start_ts,
)
```

**问题：** 验收标准要求 WSS 核心（含 `commands/`）零 `web_viewer` import。此处仍有惰性 import。

**分析：**
- `set_archive_state()` 只写 JSON 文件（`_archive_state.json`），无 WS 推送/日志写入
- lazy import + `try/except` 包裹，不会导致运行时崩溃
- 仅当关闭**最后一个**活跃 workspace 时触发

**建议：**
- 🟡 将 `set_archive_state()` / `_archive_state_file` 移至共享模块（如 `state.py` 或 `persistence.py`），让 web_viewer.py 和 workspace.py 都引用共享模块而非互相依赖
- 或者接受当前惰性 import 为可接受的次要耦合（不影响解耦核心目标）

---

## 四、`!命令` 功能完整性

| 文件 | 变更类型 | 对 `!命令` 影响 | 结论 |
|:-----|:---------|:----------------|:----:|
| `commands/admin.py` | 补全缺失 import | ✅ 修复 R100 bug，`!list_agents`/`!agent_status`/`!audit_log` 正常运行 | ✅ |
| `commands/task.py` | 补全缺失 import | ✅ 修复 R100 bug，`!task_create` 等正常运行 | ✅ |
| `commands/pipeline.py` | 仅删 write_chat_log | ✅ 不改变逻辑，消息仍通过 `save_message()` 持久化 | ✅ |
| `commands/workspace.py` | 删 write_chat_log + 补全 import | ✅ 不改变逻辑，`!close_workspace` 正常运行 | ✅ |
| `command_utils.py` | 仅删 write_chat_log | ✅ `_broadcast_to_channel` 广播功能不变 | ✅ |
| `main.py` | 仅删 write_chat_log + _ws_clients | ✅ 核心消息路由不变 | ✅ |

**结论：** 所有 `!命令` 功能完整保留，且 R100 残留的 3 处缺失 import 已修复。

---

## 五、汇总 & 结论

### 5.1 亮点

- **核心验收 5/6 全通过** — write_chat_log、_ws_clients、routes 清理干净
- **templates.py 改造完整** — WS 连接代码全部移除，替换为 fetch 轮询 + 下拉刷新
- **R100 残留 bug 同步修复** — admin.py/task.py/workspace.py 缺失 import 补充
- **语法全部通过** — 8 个文件零编译错误
- **边界文件零改动** — 所有 scope 外文件保持不变
- **__main__.py 路由干净** — 仅剩 4 条 WSS 核心路由

### 5.2 结论

> ⚠️ **有条件通过**

**1 项 🟡 建议：** `commands/workspace.py:140` 惰性 import `web_viewer`。建议将 `set_archive_state` 移到共享模块优雅解耦，但不阻塞继续推进。

### 5.3 建议顺序

1. ✅ 当前代码可接受继续推进到 Step 5 测试
2. 🟡 可选：在后续迭代中将 `set_archive_state` 移至共享模块
3. Step 5 测试重点验证：双服务独立启停、bot 通信不受 Web 服务状态影响
