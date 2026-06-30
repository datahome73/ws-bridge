# R60 技术方案 — 系统消息中 agent ID → 角色名/bot 名 显示

> **版本：** v1.0
> **状态：** 📋 定稿待编码
> **架构师：** 🏗️ Arch
> **日期：** 2026-06-30
> **基于：** `docs/R60/R60-product-requirements.md` v1.0 ✅ + `docs/R60/WORK_PLAN.md` v1.0 ✅
> **基线：** origin/dev @ ad3d174

---

## 1. 改动总览

仅 `server/handler.py`，**1 个工具函数 + 5 处 agent_id[:N] 替换**。

### 1.1 工具函数 `_get_agent_display()`

**位置：** 放在 `_load_agent_cards()` (L863) 正下方，紧邻其定义，与 agent card 逻辑同域。

**签名与实现（需求文档 §2 方向 B 直接定稿，零偏差）：**

```python
def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
    cards = _load_agent_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]
```

**决策：不引入缓存。** `auth.get_users()` 在当前架构中是内存字典读取（`_approved_users`），5s TTL 带来的复杂度超过收益。详见设计决策 D2。

---

### 1.2 五处替换（精确行号，以 R59 基线 ad3d174 为准）

| # | 行号 | 函数 | 当前代码 | 替换为 | 说明 |
|:-:|:----:|:----|:---------|:-------|:-----|
| 1 | **L205** | `handle_auth` | `f"[注册] 新代理 {_reg_name_b1}（{agent_id[:16]}）已连接，配对码：{new_code}"` | `{_get_agent_display(agent_id)}` 替换 `{agent_id[:16]}` | 注册消息已含 `_reg_name_b1`（agent 自报名），括号内显示解析名 |
| 2 | **L210** | `handle_auth` | `f"新代理注册请求：{_reg_name}（{agent_id[:16]}）配对码：{new_code} 使用 /approve 核准"` | `{_get_agent_display(agent_id)}` 替换 `{agent_id[:16]}` | Admin 通知中的 agent ID |
| 3 | **L1803** | `_send_to_agent` | `f"[定向通知 @{agent_id[:12]}] {text}"` | `@{_get_agent_display(agent_id)}` | 离线 fallback 写日志，无 ws_id |
| 4 | **L1820** | `_send_to_agent` | `f"[定向通知 @{agent_id[:12]}] {text}"` | `@{_get_agent_display(agent_id)}` | 发送失败后的写日志 fallback |
| 5 | **L3399** | `_notify_member_changed` | `users.get(member_id, {}).get("name", member_id[:12])` | `_get_agent_display(member_id)` | `member_name` 变量，注意此处已有 `name` 优先逻辑，替换后优先级链扩展为 4 级 |

**替换总数：** 5 处，共 ~5 行修改 + ~12 行工具函数新增 ≈ **17 行净改**。

---

### 1.3 边界审查：不需改的类似位置

以下位置虽有 `agent_id[:N]` 但 **不改**，理由如下：

| 行号 | 代码 | 不改理由 |
|:----:|:-----|:---------|
| L153 | `logger.info("Agent %s authenticated...", agent_id[:20], ...)` | logger.info 日志工具，需求文档 §4 明确排除 |
| L171 | `logger.info("Pushed %d offline-queued msgs to %s", ..., agent_id[:12])` | 同上 — 运维日志 |
| L179 | `auth.get_users().get(agent_id, {}).get("name", agent_id[:12])` | 已有 name 优先，agent_id[:12] 是最后 fallback，非系统消息展示 |
| L181 | `logger.info("Agent %s auto-approved via code", agent_id[:20])` | 日志工具，排除 |
| L202 | `logger.info("Agent %s in registration channel...", agent_id[:20], ...)` | 日志工具，排除 |
| L252 | `logger.info("Offline push: %d msgs delivered to %s after 3s", ..., agent_id[:12])` | 日志工具，排除 |
| L254 | `logger.info("Offline push: %d msgs for %s expired...", ..., agent_id[:12])` | 日志工具，排除 |
| **L266** | `auth.get_users().get(_approved_id, {}).get("name", _approved_id[:12])` | 变量 `_approved_name` — 已有 name 优先 |
| **L268** | `f"[核准] 管理员已核准代理 {_approved_name}（{_approved_id[:16]}）..."` | ❗系统消息残留 agent_id，建议改 `_get_agent_display(_approved_id)` **但作为 Step 3 可选优化**（需求文档未列，延至可选方向） |
| L2502 | `card.get("display_name", card.get("name", agent_id[:12]))` | `!agent_card` 命令输出，非系统消息 — 保留 |
| L2544 | `card.get("display_name", agent_id[:12])` | 同上 — `!agent_card set` 命令输出 |
| L2508 | `"Card for " + agent_id[:24]` | 同上 — 命令展示 |
| L2559 | `"No card for agent " + agent_id[:24]` | 同上 — 命令错误提示 |
| L2562 | `"Deleted card for " + agent_id[:24]` | 同上 — 命令反馈 |
| L3034 | `users.get(agent_id, {}).get("name", agent_id[:12])` | 已有 name 优先，且是 `!agent_status` 命令输出 |

**特别注意 L268：** `write_chat_log("系统", f"[核准] 管理员已核准代理 {_approved_name}（{_approved_id[:16]}）...")` — 这是系统消息但需求文档未列在方向 A 的 5 处中。方案建议编码阶段一并替换，归类为**方向 A+（同族优化）**，不视为 scope creep（同函数同模式，5 行变 6 行）。

---

## 2. 改动详解

### 2.1 工具函数插入（L863 之后）

```python
# ── R60 F-19: Unified agent display resolution ──────────────
def _get_agent_display(agent_id: str) -> str:
    """Unified agent display name: display_name > name > role > agent_id[:12]"""
    cards = _load_agent_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]
```

### 2.2 替换细节

**L205:** `handle_auth` 注册消息
```
-    write_chat_log("系统", f"[注册] 新代理 {_reg_name_b1}（{agent_id[:16]}）已连接，配对码：{new_code}")
+    write_chat_log("系统", f"[注册] 新代理 {_reg_name_b1}（{_get_agent_display(agent_id)}）已连接，配对码：{new_code}")
```

**L210:** `handle_auth` admin 通知
```
-    _notify_content = f"新代理注册请求：{_reg_name}（{agent_id[:16]}）配对码：{new_code} 使用 /approve 核准"
+    _notify_content = f"新代理注册请求：{_reg_name}（{_get_agent_display(agent_id)}）配对码：{new_code} 使用 /approve 核准"
```

**L1803:** `_send_to_agent` 离线 fallback
```
-            write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")
+            write_chat_log("系统", f"[定向通知 @{_get_agent_display(agent_id)}] {text}")
```

**L1820:** `_send_to_agent` 发送失败 fallback
```
-        write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")
+        write_chat_log("系统", f"[定向通知 @{_get_agent_display(agent_id)}] {text}")
```

**L3399:** `_notify_member_changed` 成员变更
```
-    member_name = users.get(member_id, {}).get("name", member_id[:12])
+    member_name = _get_agent_display(member_id)
```

### 2.3 可选：L268 同族优化（建议编码阶段一并做）
```
-    write_chat_log("系统",
-        f"[核准] 管理员已核准代理 {_approved_name}（{_approved_id[:16]}）角色={data.get('role', 'member')}")
+    _approved_display = _get_agent_display(_approved_id)
+    write_chat_log("系统",
+        f"[核准] 管理员已核准代理 {_approved_display} 角色={data.get('role', 'member')}")
```
（去掉括号 ID，若保留原始 `_approved_name` 在括号中则可改为 `{_approved_name}（{_get_agent_display(_approved_id)}）`）

---

## 3. 测试策略

### 3.1 单元测试 `tests/R60_test.py`

| # | 测试用例 | 断言数 |
|:-:|:---------|:------:|
| 1 | `_get_agent_display` — `display_name` 优先（card 有 display_name） | 2 |
| 2 | `_get_agent_display` — `name` 次级（card 无 display_name，用户有 name） | 2 |
| 3 | `_get_agent_display` — `role` 三级（card 无 display_name，用户无 name 但有 role） | 2 |
| 4 | `_get_agent_display` — `agent_id[:12]` 回退（无 card、无用户） | 2 |
| 5 | `_get_agent_display` — card 存在但字段不全（部分缺失） | 2 |
| 6 | 验证 5 处替换位置的代码字符串（静态 grep 确认替换） | 5 |
| 7 | 回归—现有 R58 测试 + R57 测试不因新函数影响 | 2 |

**预估断言：** ≥17 个（含代码静态验证）

### 3.2 回归验证

| 检查项 | 方法 |
|:-------|:-----|
| 语法正确 | `python -c "import ast; ast.parse(open('server/handler.py').read())"` |
| agent_id[:N] 残留 | `grep -n "agent_id\[.*:" server/handler.py` — 仅剩 logger.info 和 agent card 命令 |
| member_id[:N] 残留 | `grep -n "member_id\[.*:" server/handler.py` — 仅剩 L266 可选优化 |
| _get_agent_display 引用 | `grep -c "_get_agent_display" server/handler.py` — 至少 5 处 |
| R58 测试全通过 | `python -m pytest tests/R58_test.py -v 2>&1` |
| R57 测试全通过 | `python -m pytest tests/R57_test.py -v 2>&1` |

---

## 4. 风险评估

| 风险 | 等级 | 缓解措施 |
|:-----|:----:|:---------|
| `_load_agent_cards()` 异常（文件损坏） | 🟡 | 函数内部 try/except，返回空 dict，退化到 name/fallback |
| `auth.get_users()` 空（系统未初始化） | 🟡 | 空 dict 时 `get()` 返回 None，最终回退 `agent_id[:12]` |
| 某个 agent 既无 card 又无 name/role | 🟢 | 显示 `agent_id[:12]` 等价于现状，无退化 |
| 引入 `_get_agent_display` 后遗忘 logger.info 位置 | 🟢 | grep 验证步骤 catch |
| scope creep（编码者多改其他位置） | 🟡 | 审查者打回 |

---

## 5. 验收确认

| # | 验收标准 | 验证方式 |
|:-:|:---------|:---------|
| ✅-1 | `_admin` 注册通知显示 bot 名而非 agent ID | 检查 L205、L210 替换后的输出 |
| ✅-2 | `_notify_member_changed` 显示角色/名 | 检查 L3399 替换后的输出 |
| ✅-3 | 工具函数优先级正确 | 单元测试 #1-#5 |
| ✅-4 | `_cmd_pipeline_status` 不受影响 | 回归测试 |
| ✅-5 | 100% 回归 | R58 + R57 测试全通过 |
| ✅-6 | grep 零残留 agent_id 在系统消息中 | shell 验证 |

---

## 6. 设计决策

| # | 决策 | 理由 |
|:-:|:-----|:------|
| D1 | `_get_agent_display()` 放在 `_load_agent_cards()` 下方 | 与 agent card 逻辑同域，复用卡片数据路径 |
| D2 | 不引入 5s TTL 缓存 | `auth.get_users()` 已是内存读取，缓存增加复杂度无收益 |
| D3 | 范围严控 5+1 处（L268 可选） | 遵循 WORK_PLAN §0.1 scope creep 禁令 |
| D4 | 测试用静态 grep + 单元测试，不用集成测试 | 改动极小（17 行），集成环境需 WebSocket 连接，代价过高 |
| D5 | 代理自报名（name 字段）保留在注册消息中 | `[注册] 新代理 {自报名}（{解析名}）` — 双信息完整 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:-----|
| v1.0 | 2026-06-30 | R60 技术方案定稿 — 5+1 处替换 + 工具函数 + 测试策略 |
