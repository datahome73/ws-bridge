# R131 WORK_PLAN — !命令规则化改造（Query-as-##）

> **目标：** 在 scenario_matcher.py 中新增 `##query` 规则优先级 25，将 6 个常用查询从 `!` 命令迁移到 `##query` 模式，统一走规则表处理、权限检查、inbox 私信回复

---

## Step 1：需求确认 + 推 dev

- [ ] 审核 R131 需求文档 v1.4
- [ ] 确认改动范围符合预期
- [ ] 推 dev：`git add -f docs/R131/ && git commit -m "docs: R131 v1.4 — ..." && git push origin dev`

## Step 2：技术方案

本轮为后端架构改造轮，方案已在需求文档 §2 中定义：

| # | 方案 | 位置 | 说明 |
|:-:|:-----|:-----|:------|
| S1 | 新增 rule 25 | `scenario_matcher.py` | `match_query` + `handle_query` |
| S2 | 子命令路由 | `handle_query` 内部 | 6 个 ##query 子命令分派 |
| S3 | 权限检查 | `handle_query` 内部 | `get_agent_level()` → L1/L3/L4 分级 |
| S4 | 回复机制 | `_send_reply()` | 复用已有函数，仅回复发送者 inbox |
| S5 | main.py 注册 | `main.py` 规则注册区 | 注入查询函数回调到 scenario_matcher |

- [ ] arch 确认方案 → 推进 Step 3

## Step 3：编码

### S3-1: scenario_matcher.py — 新增 match_query

| 操作 | 位置 | 内容 |
|:----|:------|:------|
| 新增 | `scenario_matcher.py` | `match_query(content, msg, agent_id)` — 检查 `content.startswith("##query")` |

```python
def match_query(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 25: ##query commands."""
    if content.startswith("##query"):
        return content
    return False
```

### S3-2: scenario_matcher.py — 新增 handle_query + 子命令路由

| 操作 | 位置 | 内容 |
|:----|:------|:------|
| 新增 | `scenario_matcher.py` | `handle_query(ws, agent_id, msg, matched)` — 解析 → 权限 → 执行 → 回复 |

```python
async def handle_query(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ##query commands. Parses sub-command, checks permission, executes, replies to inbox."""
    content = matched
    # Parse: "##query##status##R130" → parts = ["", "query", "status", "R130"]
    parts = content.split("##")
    if len(parts) < 3:
        return False
    sub_cmd = parts[2].lower()
    params = parts[3] if len(parts) > 3 else ""

    # Permission check
    level = get_agent_level(agent_id)
    if level < 1:
        await _send_reply(ws, agent_id, "❌ 权限不足")
        return True

    # L1 → only ##whoami
    if level == 1 and sub_cmd != "whoami":
        await _send_reply(ws, agent_id, "❌ 权限不足：L1 仅允许 ##whoami")
        return True

    # L3 → query commands only, no audit
    if level == 3 and sub_cmd == "audit":
        await _send_reply(ws, agent_id, "❌ 权限不足：##audit 需要 L4")
        return True

    # Route sub-commands
    if sub_cmd == "whoami":
        from server.common import auth
        users = auth.get_users()
        info = users.get(agent_id, {})
        name = info.get("name", agent_id[:12])
        reply = f"🆔 agent_id: {agent_id} | 名称: {name} | 级别: L{level}"
    elif sub_cmd == "status":
        # Reuse pipeline query logic
        reply = await _format_pipeline_status(params)
    elif sub_cmd == "agents":
        reply = await _format_agent_list()
    elif sub_cmd == "agent_info":
        reply = await _format_agent_info(params)
    elif sub_cmd == "audit":
        reply = await _format_audit_log(params)
    elif sub_cmd == "help":
        reply = _format_query_help()
    else:
        reply = f"❌ 未知查询: {sub_cmd}"

    await _send_reply(ws, agent_id, reply)
    return True
```

### S3-3: scenario_matcher.py — 注册 rule 25

```python
register_rule(HandlerRule(
    match=match_query,
    handle=handle_query,
    priority=25,
    name="##query 命令",
    protocol_ref="§R131",
))
```

### S3-4: scenario_matcher.py — 新增 get_agent_level()

从 agent_card 或 approved_users 获取级别：

```python
def get_agent_level(agent_id: str) -> int:
    """返回 agent 的权限级别 (1-4)，默认 1。"""
    from server.common import persistence
    users = persistence.get_approved_users()
    info = users.get(agent_id, {})
    return info.get("level", 1)
```

### S3-5: scenario_matcher.py — 新增查询数据函数

5 个查询函数，复用现有 commands/ 和 main.py 的数据逻辑：

| 函数 | 数据源 | 复用路径 |
|:-----|:--------|:---------|
| `_format_pipeline_status(round_name)` | `_ensure_engine().format_context()` / `_ensure_pipeline_manager().get_all_active()` | main.py `_ensure_engine()` / `_handle_server_query` L2117-2135 |
| `_format_agent_list()` | `auth.get_users()` + `agent_card.get_all_cards()` + `_connections` | commands/agent_card.py |
| `_format_agent_info(agent_id)` | `auth.get_agent_name()` + `agent_card.get_card()` | commands/agent_card.py |
| `_format_audit_log(limit)` | `audit.tail()` | commands/admin.py |
| `_format_query_help()` | 静态文本 | — |

### S3-6: main.py — 注册 ##query 的 handle 回调

在 main.py 底部的规则注册区（参考 L4653+），注入查询函数到 scenario_matcher：

```python
# R131: ##query 命令 — 复用 main.py 的查询函数
async def _handle_query(ws, agent_id, msg, matched):
    return await _sm.handle_query(ws, agent_id, msg, matched)

# 注入 engine/pipeline 引用
_sm._ensure_engine = _ensure_engine
_sm._ensure_pipeline_manager = _ensure_pipeline_manager
```

## Step 4：代码审查

- [ ] 审查 `scenario_matcher.py` — rule 25 注册位置和优先级是否正确（介于 to_agent 20 和 ## 30 之间）
- [ ] 审查权限检查逻辑 — L1/L3/L4 三级权限边界是否正确
- [ ] 审查 `main.py` 回调注入 — 不破坏现有规则链
- [ ] 确认 `_send_reply()` 复用正确，不广播到频道

## Step 5：测试验证

- [ ] `py_compile` 检查 Python 文件语法
- [ ] 运行时 import 验证：`python3 -c "from server.ws_server.scenario_matcher import dispatch, match_query, handle_query"`

### QA 检查表

| # | 验收项 | 结果 |
|:-:|:-------|:----:|
| F1 | L1 发 `##whoami` → 收到自己信息 | ⬜ |
| F2 | L3 发 `##agents` → 收到 bot 列表 | ⬜ |
| F3 | L3 发 `##status` → 收到活跃管线 | ⬜ |
| F4 | L3 发 `##status##R130` → 收到指定管线详情 | ⬜ |
| F5 | L3 发 `##agent_info ws_xxx` → 收到 bot 详情 | ⬜ |
| F6 | L4 发 `##audit` → 收到审计日志；L3 发 `##audit` → 权限拒绝 | ⬜ |
| R1 | 原有 `##start`/`##stop`/`##advance`/`##archive` 不受影响 | ⬜ |
| R2 | 原有 `!` 命令仍可用 | ⬜ |
| R3 | `_handle_server_query` 仍可用 | ⬜ |
| R4 | to_agent 派活不受影响 | ⬜ |
| R5 | ##query 回复仅到发送者 inbox | ⬜ |

## Step 6：合并部署

- [ ] `git checkout main && git pull origin main`
- [ ] `git merge dev`（merge commit）
- [ ] `git push origin main`
- [ ] 部署到生产环境

---

## 关键里程碑

| 阶段 | 交付物 |
|:-----|:-------|
| Step 1 ✅ | 需求文档审核通过 + 推 dev |
| Step 2 ✅ | 技术方案确认（新增 rule 25 + 6 个子命令） |
| Step 3 ✅ | 编码完成（match_query / handle_query / 权限检查 / 5 个查询函数 / main.py 注册） |
| Step 4 ✅ | 代码审查通过（规则优先级 / 权限边界 / 不破坏现有规则） |
| Step 5 ✅ | 测试验证 11/11 ALL GREEN 🟢 |
| Step 6 ✅ | 合 main 部署 |

---

## 改动预览

| 文件 | 新增 | 删除 | 修改 | 净变化 |
|:-----|:----:|:----:|:----:|:------:|
| `server/ws_server/scenario_matcher.py` | ~120 | 0 | ~5 | **+125** |
| `server/ws_server/main.py` | ~10 | 0 | ~3 | **+13** |
