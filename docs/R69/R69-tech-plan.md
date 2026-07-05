# R69 技术方案 — 收件箱上下文增强 + 待办清理 🔄

> **版本：** v1.0 ✅
> **状态：** ✅ 定稿
> **架构师：** 👷 Arch
> **基于工作计划：** docs/R69/WORK_PLAN.md v1.0 ✅
> **基线：** `a92e9e5`

---

## 1. 改动汇总

| # | 改动 | 位置 | 操作 | 行数 |
|:-:|:-----|:-----|:----|:----:|
| 1 | `step_outputs` 扩展：+title/+output_desc/+summary/+artifact_url | handler.py L2428-2432 | 修改 dict | +4 |
| 2 | 新增 `_infer_artifact_url()` 函数 | handler.py ~L1165 后 | 新增函数 | +10 |
| 3 | `_send_inbox_task` 消息模板增强 | handler.py L2262-2275 | 替换字符串 | ±8 |
| 4 | `_send_inbox_task` 函数签名 + payload 补 agent_id | handler.py L2247 + L2287-2290 | 修改 | +3 |
| 5 | step_complete 调用传 `sender_id` | handler.py L2581 | 加参数 | +1 |
| 6 | step_handoff 调用传 `sender_id` | handler.py L3203 | 加参数 | +1 |
| 7 | 新增 `!workspace_reset` 命令 | handler.py _ADMIN_COMMANDS + 新函数 | 新增 | +15 |
| 8 | `!pipeline_status` 展示增强 | handler.py L516-520 | 修改 | +5 |
| 9 | 文档清理 + TODO 更新 | docs/ + gateway-plugin/ | 修改 | 0 |
| | **合计** | | | **~47行净增** |

---

## 2. 精确代码改动

### 2.1 新增 `_infer_artifact_url()` — ~L1165 后

```python

# ── R69 A1: Auto-infer artifact URL by step type ──
_R69_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"

def _infer_artifact_url(step_name: str, round_name: str) -> str:
    """Auto-infer artifact URL based on step type. Returns '' if unknown."""
    step_urls = {
        "step2": f"{_R69_REPO_BASE}/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"{_R69_REPO_BASE}/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"{_R69_REPO_BASE}/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")
```

> 注：`_R69_REPO_BASE` 常量名可复用已有 `_R62_REPO_BASE`（handler.py 中已存在），避免新增重复常量。若 `_R62_REPO_BASE` 值相同，直接用 `_R62_REPO_BASE`。

### 2.2 `step_outputs` 扩展 — L2428-2432

```python
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "title": step_config.get(step_name, {}).get("title", step_name),
            "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
            "summary": params.get("summary", step_config.get(step_name, {}).get("output_desc", "")),
            "artifact_url": params.get("artifact_url",
                _infer_artifact_url(step_name, round_name)),
            "timestamp": time.time(),
        }
```

### 2.3 `_send_inbox_task` 函数签名 — L2247

```python
    pm_agent_id: str = "system",  # ← R69 B1
```

完整签名：

```python
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
    pm_agent_id: str = "system",  # ← R69 B1
) -> None:
```

### 2.4 `_send_inbox_task` 消息模板 — L2262-2275 替换

旧代码（L2262-2275）全部替换为新模板：

```python
    # ── R69 A3: Build rich context from step_outputs ──
    _pstate_step_outputs = _pstate.get("step_outputs", {})
    _prev_step_key = None
    if _pstate_step_outputs:
        for _sk in reversed(sorted(_pstate_step_outputs.keys(), key=_step_sort_key)):
            if _sk != next_step:
                _prev_step_key = _sk
                break
    _prev_section = ""
    if _prev_step_key:
        _prev_out = _pstate_step_outputs[_prev_step_key]
        _prev_sha = _prev_out.get("sha", "")[:7]
        _prev_title = _prev_out.get("title", _prev_step_key)
        _prev_summary = _prev_out.get("summary", "")
        _prev_url = _prev_out.get("artifact_url", "")
        _prev_section = f"🏗️ 前序 Step {_prev_step_key.replace('step','')}「{_prev_title}」✅ ({_prev_sha})\n"
        if _prev_summary:
            _prev_section += f"  └ 💡 {_prev_summary}\n"
        if _prev_url:
            _prev_section += f"  └ 🔗 {_prev_url}\n"

    requirements_url = _pconfig.get("requirements_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md")
    plan_url = _pconfig.get("work_plan_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md")

    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_prev_section}\n"
        f"📄 参考资料:\n"
        f"  📄 需求：{requirements_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n\n"
        f"🎯 你的任务: 请按技术方案完成 {next_step}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"完成后: git push dev → !step_complete {next_step} --output <sha>"
    )
```

> **注意：** 旧代码中 `req_url` 和 `plan_url` 是从 `_pconfig` 读取的（L2254-2259）。新模板中直接内联读取这两个 URL，可以合并到 `_pstate` / `_pconfig` 读取段（L2251-2252 已有）。**实际上** `_pstate` 和 `_pconfig` 已经在 `_send_inbox_task` 开头读取（L2251-2252），所以内联读取即可，不需要额外变量。

### 2.5 inbox_payload 补齐 agent_id — L2287-2290

```python
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "agent_id": pm_agent_id,       # ← R69 B1
        "from_agent": pm_agent_id,     # ← R69 B1
        "content": inbox_msg, "ts": time.time(),
    })
```

### 2.6 step_complete 调用传 `sender_id` — L2581

```python
                pm_agent_id=sender_id,  # ← R69 B1
```

### 2.7 step_handoff 调用传 `sender_id` — L3203

```python
            pm_agent_id=sender_id,  # ← R69 B1
```

### 2.8 `!workspace_reset` 命令 — L3881 前插入

**命令注册：**

```python
    # ── R69 B2: Workspace reset ──
    "workspace_reset": {
        "handler": _cmd_workspace_reset, "min_role": 3, "workspace_scope": True,
        "usage": "!workspace_reset — 关闭当前工作室 + 清理管线状态 + 回大厅",
    },
```

**Handler 函数**（放在 `_cmd_step_reject` 附近，~L3870 区域之后）：

```python
async def _cmd_workspace_reset(sender_id: str, params: dict) -> str:
    """重置工作室：关闭当前工作室 + 清理管线状态 + 成员频道回大厅。"""
    sender_ch = _get_sender_channel(sender_id, params)
    if not sender_ch:
        return "❌ 无法确定当前工作区"
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 未找到活跃工作室"
    ws_id = ws_obj.id
    ws_name = ws_obj.name
    # 2. Close workspace
    close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
    # 3. Reset agent channels to lobby
    await _broadcast_active_channel(p.LOBBY)
    # 4. Clear pipeline state for this ws
    for pid, pst in list(_PIPELINE_STATE.items()):
        if pst.get("ws_id") == ws_id:
            _PIPELINE_STATE[pid]["active"] = False
    return f"✅ 工作室「{ws_name}」({ws_id[:12]}) 已重置 — 归档 + 回大厅 + 管线清理完成"
```

### 2.9 `!pipeline_status` 展示增强 — L516-520

```python
    for out_step_key, out_info in sorted(step_outputs.items(), key=lambda x: _step_sort_key(x[0])):
        sha = out_info.get("sha", "")[:7]
        title = out_info.get("title", out_step_key)
        summary = out_info.get("summary", "")
        url = out_info.get("artifact_url", "")
        line = f"    {out_step_key} {title} — {sha}"
        if summary:
            line += f"\n      └ 💡 {summary[:80]}"
        if url:
            line += f"\n      └ 🔗 {url}"
        lines.append(line)
```

---

## 3. 不改动确认

| 文件 | 确认不动 |
|:-----|:--------|
| `shared/protocol.py` | ✅ 常量已在 R68 定义 |
| `server/persistence.py` | ✅ 工具函数已在 R68 定义 |
| `server/auth.py` | ✅ 收件箱自动注册已在 R68 实现 |
| `server/workspace.py` | ✅ 工作室系统不动 |
| `server/pipeline_sync.py` | ✅ Git 同步不动 |
| `server/timeout_tracker.py` | ✅ 倒计时模块不动 |
| `server/task_store.py` | ✅ 任务状态机不动 |
| `server/web_viewer.py` | ✅ Web 端不动 |
| `gateway-plugin/` | ✅ 仅目视检查 |

---

## 4. 风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| `_send_inbox_task` 已有调用方忘记传 `pm_agent_id` | 使用默认值 `"system"`，不崩 | 参数有默认值，向下兼容 |
| `params.get("summary")` 取不到值 | 降级为 `output_desc` | 默认值处理 |
| `_pipeline_status` 在 `_cmd_list_workspaces` 函数中 | 不影响其他部分 | 修改范围仅限于 step_outputs 展示段 |
