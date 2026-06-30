# R60 技术方案 — agent ID → 角色名/ bot 名 显示

> **版本：** v1.0
> **状态：** 📝 已提交
> **基于：** `docs/R60/R60-product-requirements.md` + `docs/R60/WORK_PLAN.md`

---

## 1. 改动概述

单文件 `server/handler.py`，新增 1 个工具函数 + 替换 5 处 agent ID 显示。

### 1.1 `_get_agent_display()` 工具函数

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

**放置位置：** `_load_agent_cards()` 函数定义之后（~L870 区域），与其他工具函数相邻。

**不引入缓存：** `auth.get_users()` 在当前代码中已经是常规调用的全量读取。5 处调用的频率极低（每注册/每通知触发一次），无需 5s TTL 缓存。

### 1.2 五处替换（R59 代码基线）

| # | 原行号 | 当前代码 | 替换为 | 函数位置 |
|:-:|:------:|:---------|:-------|:---------|
| 1 | L205 | `{agent_id[:16]}` | `{_get_agent_display(agent_id)}` | `_handle_auth()` |
| 2 | L210 | `{agent_id[:16]}` | `{_get_agent_display(agent_id)}` | `_handle_auth()` |
| 3 | L1803 | `@{agent_id[:12]}` | `@{_get_agent_display(agent_id)}` | `_send_to_agent()` |
| 4 | L1820 | `@{agent_id[:12]}` | `@{_get_agent_display(agent_id)}` | `_send_to_agent()` |
| 5 | L3399 | `member_id[:12]` | `_get_agent_display(member_id)` | `_notify_member_changed()` |

**行号说明：** 以 origin/dev（R59 合并后）的 `server/handler.py` 为准。

### 1.3 不需要改的地方

- `_cmd_pipeline_start` 返回值 — 已通过 `_cmd_create_workspace` 显示名称 ✅
- `_cmd_pipeline_status` — R57 已加名称解析 ✅
- `logger.info("Agent %s ...", agent_id[:20], ...)` — 日志保留 ID 用于 Debug
- `write_chat_log("系统", f"[回退广播 @{ws_id}] ...")` — 已用 ws_id 而非 agent_id
- Web 端渲染 — 通过 `from_name` 字段显示

---

## 2. 测试策略

### 2.1 自动化测试 `tests/R60_test.py`

```python
# 工具函数测试（4 条优先级路径）
- display_name 存在 → 返回 display_name
- display_name 无，name 存在 → 返回 name
- display_name 无，name 无，role 存在 → 返回 role
- 全无 → 返回 agent_id[:12]
# 5 处替换读风测试（文件内容 grep）
- grep L205 应无 agent_id[:16]
- grep L210 应无 agent_id[:16]
- grep L1803 应无 agent_id[:12]
- grep L1820 应无 agent_id[:12]
- grep L3399 应无 member_id[:12]
# 回归测试（R57 + R58 测试全部通过）
- import tests.R57_test
- import tests.R58_test
```

### 2.2 人工验证

| # | 验证步骤 | 预期 |
|:-:|:---------|:-----|
| V1 | Web 端注册新 bot | `新代理注册请求：Bot名（全名）已连接` |
| V2 | 工作室添加成员 | `Bot名 加入了工作室` |
| V3 | pipeline_status 无变化 | 仍显示名称（不改 ✅） |

---

## 3. 风险与注意事项

| # | 风险 | 影响 | 缓解 |
|:-:|:-----|:----:|:-----|
| R1 | `_load_agent_cards()` 在模块顶层是开文件全量读，5 处调用每处都读一次 | 低（每个调用频次极低） | 若实测瓶颈可加缓存，本轮不引入 |
| R2 | `agent_id[:12]` 可能在其他未扫描到的代码路径中使用 | 低 | `grep -n 'agent_id\[.*:\|member_id\[.*:'` 确认零残留 |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:-----|
| v1.0 | 2026-06-30 | R60 技术方案定稿 — 1 工具函数 + 5 处替换 |
