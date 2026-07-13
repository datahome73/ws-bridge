# R109 测试报告 🦐

> **轮次：** R109 — 架构大重构 `server/` → `ws_server/` + `web_ui/` + `common/`
> **测试日期：** 2026-07-14
> **测试人：** 泰虾
> **测试模式：** 源码级分析（无运行时依赖）

---

## 总览

| 指标 | 数值 |
|:-----|:-----|
| 测试总数 | 37 项 |
| ✅ 通过 | 26 |
| ❌ 失败 | 11 |
| ⚠️ 警告 | 3 |
| **通过率** | **70.3%** |

## 逐项结果

### A — 代码隔离 ✅ 5/5

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `ws_server/` 纯 WSS 核心 | ✅ | 无 web 相关文件 |
| 2 | `web_ui/` 零 `ws_server` import | ✅ | 仅 `server.common.*` |
| 3 | `ws_server` 零 web 关键词残留 | ✅ | BIND_TEMPLATE/CHAT_TEMPLATE 等全无 |
| 4 | `server/` 旧文件已删除 | ✅ | web_service.py/web_viewer.py/config.py/entrypoint.py |
| 5 | 全部 .py 语法正确 | ✅ | 26 文件编译通过 |

### B — Config 精简 ❌ 5/7 ⚠️ 2/7

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `common/config.py` 存在 | ✅ | 26 行，精简 |
| 2 | `HTTP_PORT` 已删除 | **❌** | 死代码，无任何引用 |
| 3 | `APP_ID` 已删除 | **❌** | 死代码，无引用 |
| 4 | `ADMIN_AGENTS` 已删除 | ⚠️ | 被 `ws_server/__main__.py` 引用，合法共享 |
| 5 | `DISPATCH_SENDER_ID` 已删除 | ⚠️ | 被 `ws_server/__main__.py` 引用，合法共享 |
| 6 | `AUTO_DISPATCH_ENABLED` 在 config 中 | **❌** | ⚠️ **运行时 bug** — `main.py L2470` 引用 `config.AUTO_DISPATCH_ENABLED` 但 `common/config.py` 无此属性，触发 `AttributeError` |
| 7 | `PIPELINE_STEP_MAP` 在本 package 内 | ✅ | 在 `main.py` 中以字面量形式存在 |

### C — 前端减法 ❌ 5/5

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `BIND_TEMPLATE` 已删除 | **❌** | `server/web_ui/templates.py L4` 仍存在 |
| 2 | `🔧 管理员` Tab 已删除 | **❌** | `TAB_STATE` 仍有 3 个 Tab |
| 3 | `wsListBtn` 已删除 | **❌** | 前端仍有工作室按钮 |
| 4 | `handle_api_bind/check/approve_web` 已删除 | **❌** | handler 和路由均未删除 |
| 5 | `/api/bind/check/approve_web` 路由已删除 | **❌** | 全部 3 条路由仍注册 |

### D — 数据层 ✅ 9/9

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `ws_server/message_store.py` 存在 | ✅ | 8361 chars，完整读写版 |
| 2 | `common/message_store.py` 存在 | ✅ | 4649 chars，只读副本版 |
| 3 | `ws_server ms` 有 `save_message/init_db/read 系列` | ✅ | 6/6 |
| 4 | `common ms` 有只读函数 | ✅ | 4/4 |
| 5 | `common/persistence.py` 存在 | ✅ | 2559 chars |
| 6 | `persistence` 有 `get_api_keys/save_api_keys/approved_users` | ✅ | 5/5 |
| 7 | `common/auth.py` 存在 | ✅ | 4403 chars |

### E — Bot 状态 ❌ 3/3

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `ws_server` 写入 `_bot_status.json` | **❌** | 未实现 — 无任何文件写入逻辑 |
| 2 | `web_ui` 读取 `_bot_status.json` | **❌** | 仍用 HTTP 轮询：`_fetch_bot_status()` → `http://127.0.0.1:/api/status` |
| 3 | HTTP 轮询已移除 | **❌** | `web_ui/main.py:29` 仍在 HTTP 轮询，未改为文件读取 |

### F — 管线消息入库 ✅ 1/1

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `_auto_dispatch` 内消息入库 | ✅ | 间接通过 `_send_to_agent()` 入库 |
| 2 | `_handle_server_relay` 内消息入库 | ✅ | 直接 `ms.save_message()` 调用 |

---

## ❌ 失败项详述

### 1. Config 死代码

`server/common/config.py` 中两个无引用的配置项：

```python
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
```

**根因：** `server/config.py` → `server/common/config.py` 迁移时未做减法。
**修复：** 删除这两行。

### 2. `AUTO_DISPATCH_ENABLED` 运行时 bug

`server/ws_server/main.py` L2470：
```python
from server.common import auth, config, persistence  # config = common.config
...
if not config.AUTO_DISPATCH_ENABLED:  # ← AttributeError: no attribute
```

`server/common/config.py` 已无 `AUTO_DISPATCH_ENABLED`，该属性在迁移中丢失。

**影响：** 自动派活功能触发时直接崩溃。
**修复：** 在 `common/config.py` 中加回：
```python
AUTO_DISPATCH_ENABLED: bool = os.environ.get("WS_AUTO_DISPATCH", "1") == "1"
```

### 3. 前端减法未完成（5 项）

| 文件 | 代码段 | 状态 |
|:-----|:-------|:-----|
| `web_ui/templates.py:4` | `BIND_TEMPLATE = r"""..."""` | 整段未删 |
| `web_ui/templates.py:135-139` | `TAB_STATE` 含 `tab2: '🔧 管理员'` | 3 Tab 未缩为 2 |
| `web_ui/templates.py:110` | `wsListBtn` | 工作室按钮未删 |
| `web_ui/viewer.py:268,273,357` | `handle_api_bind/check/approve_web` | 3 个 handler 未删 |
| `web_ui/viewer.py:687-690` | `/api/bind /check /approve_web` 路由 | 3 条路由未删 |

**根因：** Step 3（编码）只做了目录重组和 import 调整，前端减法被搁置。

### 4. Bot 状态文件传递未实现（3 项）

需求明确（R109 需求文档 3.7 节）：
> **不用 HTTP 轮询，用文件传递。** ws-server 每 10 秒写入 `data/_bot_status.json`，web-ui 每次刷新页面时读取该文件。

实际实现：
- `ws_server`：无任何定时写入 `_bot_status.json` 的逻辑
- `web_ui/main.py:29`：仍然 HTTP 轮询 `http://127.0.0.1:/api/status`
- `web_ui/viewer.py:500`：通过 `_BOT_STATUS_CACHE` 获取（同样是 HTTP 缓存的）

**修复方向：**
1. `ws_server/__main__.py` 或 `ws_server/main.py` 添加定时任务（每 10 秒）：
   - 收集 `_connections` 中的在线 agent 列表
   - 写入 `DATA_DIR / "_bot_status.json"`
2. `web_ui/main.py`：
   - 删除 `_fetch_bot_status()` HTTP 轮询
   - 删除 `_poll_bot_status_loop()`
   - 改为直接读 `DATA_DIR / "_bot_status.json"` 文件
   - 删除 aiohttp 依赖（如果无其他用途）

---

## ⚠️ 警告项

### `ADMIN_AGENTS` 和 `DISPATCH_SENDER_ID`

需求文档要求删除这两个配置项，但 `ws_server/__main__.py` 仍引用它们：

```python
from server.common.config import HOST, PORT, DATA_DIR, ADMIN_AGENTS, DISPATCH_SENDER_ID
```

**评估：** 属于**共享配置**（被 ws-server 使用），不是死代码，不需要删除。需求文档应更新以反映实际架构。

### 管理员 Tab 是否保留

`TAB_STATE` 的 `tab2`（管理员频道）在 `templates.py` 中有完整的渲染逻辑（L229-231），且 `selectTab()` 有对应的 L263 分支。如果保留管理员 Tab 是业务要求，则需求文档需要更新。

---

## ✅ 通过亮点

### 代码隔离 ✅✅✅✅✅

- `web_ui/` 所有 `.py` 文件只 import `server.common.*` + `server.web_ui.*`，零 `ws_server` 引用
- `ws_server/` 所有 `.py` 文件只 import `server.common.*` + `shared.protocol`，零 web 关键词
- 没有循环导入 —— `is_workspace_admin()` 使用延迟导入（lazy import）避免启动时依赖

### 数据层拆分 ✅✅✅✅✅✅✅✅✅

common/ 层 4 个模块分工明确：
- `common/auth.py` — api_key 认证、权限检查（不含 web session/OAuth）
- `common/config.py` — env 读取（双进程共享）
- `common/message_store.py` — 只读 SQLite 查询
- `common/persistence.py` — JSON 持久化（api_keys, approved_users）

ws_server 内部另有完整读写版 `message_store.py`（含 `save_message` 写入函数）。

---

## 建议修复优先级

| 优先级 | 问题 | 工作量 | 影响 |
|:------|:-----|:------|:-----|
| 🔴 P0 | `AUTO_DISPATCH_ENABLED` 运行时 bug | 1 行 | 自动派活启动即崩溃 |
| 🟡 P1 | Bot 状态文件传递未实现 | 2 个函数 | 依赖解耦不完整 |
| 🟡 P1 | 前端减法 5 项未清理 | 删除代码 | 不符需求 |
| 🟢 P2 | `HTTP_PORT`/`APP_ID` 死代码 | 2 行删除 | 代码整洁 |
| ⬜ P3 | 需求文档与实现对齐（admin tab 保留/删除决策） | 文档更新 | 团队认知对齐 |

---

## 测试脚本

`docs/R109/test_r109_acceptance.py`

运行方式：
```bash
python3 docs/R109/test_r109_acceptance.py
```

测试类型：纯源码级分析（grep + AST + `compile()` 语法检查），无需运行服务端。
