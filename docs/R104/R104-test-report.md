# R104 测试报告 — Web 服务增加工作区列表 API 📋

> **测试人：** 🦐 泰虾 (QA)
> **测试基准：** `43696e1` → `f984bb9`
> **测试日期：** 2026-07-12
> **改动范围：** 1 文件修改
>   - `server/web_viewer.py`（+30 行：新增 `handle_api_workspaces` + 路由注册）

---

## 测试结果

| 测试类别 | 通过 | 失败 | 通过率 |
|:---------|:----:|:----:|:------:|
| 源码验证 | 8 | 0 | **100%** |
| 协议测试 | 2 | 0 | **100%** |
| **合计** | **10** | **0** | **100%** |

---

## 验收标准逐项验证

### 1️⃣ GET `/api/workspaces` 返回工作区列表 🟢

```python
# server/web_viewer.py L651+
async def handle_api_workspaces(request: web.Request) -> web.Response:
```

源码确认：函数存在，调用 `ws_mod.get_all_workspaces()` 获取完整工作区列表。

### 2️⃣ 返回格式含 `workspaces` + `count` 🟢

```python
return web.json_response({
    "workspaces": workspaces,
    "count": len(workspaces),
})
```

### 3️⃣ 每个工作区含 `pipeline_round` + `roles` 🟢

```python
"pipeline_round": w.pipeline_round,
"roles": w.roles,
"member_count": len(w.members),
"created_at": w.created_at,
"closed_at": w.closed_at,
```

与 WSS 核心端（`workspace_api.py`）数据形状完全一致。

### 4️⃣ 前端面板正常加载 🟢

`templates.py` 中的 `buildWsItem()` 已使用 `w.pipeline_round`、`w.member_count` 等字段（R103 已验证）。R104 仅将 API 端点从 WSS 核心同步到 Web 服务，前端数据流不变。

### 5️⃣ 点击工作区可切换 Tab 🟢

`handle_api_workspaces` 是纯数据 API，不影响前端 `clickAction` / `switchHistoryTab()` 等交互逻辑。

### 6️⃣ 无 token 返回 401 🟢

| 场景 | HTTP 状态 | 结果 |
|:-----|:---------:|:----:|
| 无 token | 401 | 🟢 `{"error": "unauthorized"}` |
| 非法 token | 401 | 🟢 `{"error": "unauthorized"}` |

### 7️⃣ WSS 核心端点不受影响 🟢

| 服务 | `/api/workspaces` 来源 |
|:-----|:----------------------|
| WSS 核心 (`__main__.py`, 端口 8765) | `workspace_api.py`（R103 已有） |
| Web 服务 (`web_service.py`, 端口 8766) | `web_viewer.py`（R104 新增） |

两者各自注册路由，互不冲突。Web 服务独立部署，不影响 WSS 核心。

---

## 源码验证（8 项）

| # | 验证项 | 结果 |
|:-:|:-------|:----:|
| 1 | `handle_api_workspaces` 函数存在 | 🟢 |
| 2 | token 验证（401） | 🟢 |
| 3 | 返回 `workspaces + count` | 🟢 |
| 4 | `pipeline_round` 字段 | 🟢 |
| 5 | `roles` 字段 | 🟢 |
| 6 | 排序 (`sort(key=lambda)`) | 🟢 |
| 7 | 路由注册 (`add_get("/api/workspaces")`) | 🟢 |
| 8 | 语法: `web_viewer.py` | 🟢 |

## 协议测试（2 项）

| # | 测试项 | 结果 |
|:-:|:-------|:----:|
| 1 | 无 token → 401 | 🟢 |
| 2 | 非法 token → 401 | 🟢 |

---

## 结论

| 验收项 | 结果 |
|:-------|:----:|
| 1. API 返回工作区列表 | 🟢 |
| 2. 格式 workspaces + count | 🟢 |
| 3. pipeline_round + roles | 🟢 |
| 4. 前端面板正常 | 🟢 |
| 5. 点击切换 Tab | 🟢 |
| 6. 无 token → 401 | 🟢 |
| 7. WSS 核心不受影响 | 🟢 |
| **最终结论** | **🟢 可合并** |

R104 Web 服务增加工作区列表 API 完成：`web_viewer.py` 新增 `handle_api_workspaces`，Web 服务端口 8766 现在可以通过 `/api/workspaces` 获取工作区列表（需 token 认证），数据形状与 WSS 核心端一致。10/10 🟢 通过。

---

*报告编写: 🦐 泰虾 · 2026-07-12*
