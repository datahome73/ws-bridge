# R69 工作计划 — 收件箱上下文增强 + 待办清理 🔄

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R69/R69-product-requirements.md v1.0 ✅（项目负责人审核通过）
> **基线：** `a92e9e5`（R68 合并部署完成）
> **R68 测试状态：** ✅ 37/37 全部通过

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动集中，严禁 scope creep**

| 不改入 | 说明 |
|:-------|:------|
| `shared/protocol.py` | 仅本轮的 `!workspace_reset` 可能新增常量（可选） |
| `server/persistence.py` | 不动 |
| `server/auth.py` | 不动 |
| `server/workspace.py` | 工作室系统不动 |
| `server/pipeline_sync.py` | Git 同步逻辑不动 |
| `server/timeout_tracker.py` | 倒计时模块不动 |
| `server/task_store.py` | 任务状态机不动 |
| `server/web_viewer.py` | Web 端不动 |
| `server/templates.py` | Web 模板不动 |
| `gateway-plugin/` | Gateway 层不改（仅 L-4 目视检查） |

| 不改出 | 说明 |
|:-------|:------|
| 不引入 `_render_context` 模板变量系统改造 | 收件箱消息直接硬编码读取 step_outputs |
| 不做 Web 端管线仪表盘 | 专属轮次 |
| 不做 F-3 workspace_admin 角色体系 | 专属轮次 |
| 不做 R36-B 新虾注册流程 | 专属轮次 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py`（~70 行净增）+ 文档清理，精确改动点（基于 `origin/dev` 基线 `a92e9e5`）：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | `_cmd_step_complete()` 解析 `--summary`/`--artifact-url` 参数 | handler.py L2424-2432（R66 B1 段） | +5 行 |
| 2 | A1 | `step_outputs` 扩展：+title/+output_desc/+summary/+artifact_url | handler.py L2428-2432（同上位置） | +4 行 |
| 3 | A1 | 新增 `_infer_artifact_url()` 辅助函数 | handler.py 全局函数区（~L1290 后） | +10 行 |
| 4 | A3 | `_send_inbox_task()` 消息模板增强：读取 step_outputs 渲染上下文 | handler.py L2240-2275 模板字符串 | +8 行（替换原字符串） |
| 5 | B1 | `_send_inbox_task()` 函数签名 + payload 补 `pm_agent_id`/`agent_id`/`from_agent` | handler.py L2240+ 函数签名 + payload JSON | +3 行 |
| 6 | B1 | step_complete 中 `_send_inbox_task()` 调用传 `sender_id` | handler.py L2574-2581 | +1 行 |
| 7 | B1 | step_handoff 中 `_send_inbox_task()` 调用传 `sender_id` | handler.py L3196-3204 | +1 行 |
| 8 | B2 | 新增 `!workspace_reset` 命令注册 + handler | handler.py _ADMIN_COMMANDS + 新函数 | +15 行 |
| 9 | C1 | `_pipeline_status()` 中 step_outputs 展示增强 | handler.py L516-520 | +5 行 |
| 10 | B3/B4 | 文档清理 + TODO 更新 | docs/README.md + gateway-plugin + TODO.md | 0 行代码 |

**总估算：** ~52 行净增（代码）+ 文档清理（无代码）

### 改造对照

**收件箱消息改造前后对比：**

```
当前（R68）：
  📥 任务分配 — R69 Step「编码」

  背景上下文：
    上一 Step 产出：abc1234

  参考文档：
    📄 需求：https://...
    📋 WORK_PLAN：https://...
    🔗 上一步产出：abc1234

改造后（R69）：
  📥 任务分配 — R69 Step 3「编码」
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🏗️ 前序 Step 2「技术方案」✅ (abc1234)
    └ 💡 选型:FastAPI, DB:SQLite, 兼容优先
    └ 🔗 https://.../R69-tech-plan.md

  📄 参考资料:
    📄 需求：https://...
    📋 WORK_PLAN：https://...

  🎯 你的任务: 请按技术方案完成编码
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  完成后: git push dev → !step_complete step3 --output <sha>
```

---

## 2. 管线步骤

### Step 2 — 🏗️ 技术方案（Arch）

**主角：** arch | **备用：** dev

**完成条件：** 技术方案文档推 dev，`!step_complete step2 --output <sha>`

#### 方向 A1 — `!step_complete` 新增参数（~9 行）

**位置：** `handler.py` L2424-2432（R66 B1 `step_outputs` 记录段）

当前代码：

```python
    # ── R66 B1: Record step output ──
    pstate_b1 = _PIPELINE_STATE.get(round_name)
    if pstate_b1:
        step_outputs = pstate_b1.setdefault("step_outputs", {})
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "timestamp": time.time(),
            "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
        }
```

改造为：

```python
    # ── R66 B1 + R69 A1: Record step output with context ──
    pstate_b1 = _PIPELINE_STATE.get(round_name)
    if pstate_b1:
        step_outputs = pstate_b1.setdefault("step_outputs", {})
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

> 注意：`step_complete` 函数签名中 `params` 字典由命令解析器自动处理 `--summary/-s` 和 `--artifact-url/-u` 参数——不需要额外解析代码。`params.get("summary")` 直接取到传入值。

#### 方向 A1 — `_infer_artifact_url()` 辅助函数（~10 行）

**位置：** `handler.py` 全局函数区（建议 ~L1290 后，`_step_sort_key` 之前或之后）

```python
# ── R69 A1: Auto-infer artifact URL by step type ──
_WORK_PLAN_REPO = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"

def _infer_artifact_url(step_name: str, round_name: str) -> str:
    """Auto-infer artifact URL based on step type. Returns '' if unknown."""
    step_urls = {
        "step2": f"{_WORK_PLAN_REPO}/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"{_WORK_PLAN_REPO}/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"{_WORK_PLAN_REPO}/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")
```

> 注意：常量 `_WORK_PLAN_REPO` 若已存在（`WORK_PLAN_REPO_URL` 相关区域），复用已有常量，不新增。

---

### Step 3 — 💻 编码（Dev）

**主角：** dev | **备用：** arch

**完成条件：** 5 个改动点按技术方案编码完成，git push dev，`!step_complete step3 --output <sha>`

#### 方向 A3 — `_send_inbox_task()` 消息模板增强（~8 行）

**位置：** `handler.py` L2240-2275 — 函数体中的 `inbox_msg` 字符串模板

当前代码（L2262-2275）：

```python
    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n\n"
        f"背景上下文：\n"
        f"  上一 Step 产出：{output_ref}\n\n"
        f"任务描述：\n"
        f"  请按技术方案完成 {next_step}\n\n"
        f"参考文档：\n"
        f"  📄 需求：{req_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n"
        f"  🔗 上一步产出：{output_ref}\n\n"
        f"完成后：\n"
        f"  1. git push dev\n"
        f"  2. 在工作室回复 ✅ Step 完成 + commit SHA"
    )
```

改造为：

```python
    # ── R69 A3: Build rich context from step_outputs ──
    _pstate_step_outputs = _pstate.get("step_outputs", {})
    _prev_step_key = None
    if _pstate_step_outputs:
        # Find the most recent completed step (not the current next_step)
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

    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_prev_section}\n"
        f"📄 参考资料:\n"
        f"  📄 需求：{req_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n\n"
        f"🎯 你的任务: 请按技术方案完成 {next_step}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"完成后: git push dev → !step_complete {next_step} --output <sha>"
    )
```

> ⚠️ **注意：** 当管线中只有一个 Step 完成（无前序产出）时，`_prev_step_key` 为 None → `_prev_section` 为空字符串 → 消息开头直接是 `📄 参考资料`。不需要特殊处理。

#### 方向 B1 — `_send_inbox_task()` payload 补齐 `agent_id`/`from_agent`（~5 行）

**位置：** `handler.py` L2240（函数签名）+ L2287-2290（payload JSON）

当前函数签名：

```python
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
) -> None:
```

改造为：

```python
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
    pm_agent_id: str = "system",  # ← R69 B1: Add sender agent_id
) -> None:
```

当前 payload（L2287-2291）：

```python
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "content": inbox_msg, "ts": time.time(),
    })
```

改造为：

```python
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "agent_id": pm_agent_id,       # ← R69 B1: Add agent_id
        "from_agent": pm_agent_id,     # ← R69 B1: Add from_agent
        "content": inbox_msg, "ts": time.time(),
    })
```

#### 方向 B1 — 2 处调用点传 `sender_id`

**位置 A：** Step_complete 调用（handler.py L2574-2582）

```python
            # Send full task to inbox
            await _send_inbox_task(
                target_agent_id=primary_agent,
                round_name=round_name,
                next_step=next_step,
                step_config=step_config,
                output_ref=output_ref,
                workspace_id=sender_ch,
                pm_name=pm_name,
                pm_agent_id=sender_id,  # ← R69 B1
            )
```

**位置 B：** Step_handoff 调用（handler.py L3196-3204）

```python
        await _send_inbox_task(
            target_agent_id=_h_primary_agents[0],
            round_name=round_name,
            next_step=next_step,
            step_config=step_config,
            output_ref=output_ref,
            workspace_id=ws_id,
            pm_name="PM",
            pm_agent_id=sender_id,  # ← R69 B1
        )
```

#### 方向 B2 — `!workspace_reset` 命令（~15 行）

**位置 A：** `_ADMIN_COMMANDS` 字典末尾（L3881 的 `}` 前）

```python
    # ── R69 B2: Workspace reset ──
    "workspace_reset": {
        "handler": _cmd_workspace_reset, "min_role": 3, "workspace_scope": True,
        "usage": "!workspace_reset — 关闭当前工作室 + 清理管线状态 + 回大厅",
    },
```

**位置 B：** 新 handler 函数（建议放在 `_cmd_step_reject` 附近）

```python
async def _cmd_workspace_reset(sender_id: str, params: dict) -> str:
    """重置工作室：关闭当前工作室 + 清理管线状态 + 成员频道回大厅。"""
    # 1. Find active workspace for sender
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
    # 4. Clear pipeline state
    for pid, pst in list(_PIPELINE_STATE.items()):
        if pst.get("ws_id") == ws_id:
            _PIPELINE_STATE[pid]["active"] = False
    return f"✅ 工作室「{ws_name}」({ws_id[:12]}) 已重置 — 归档 + 回大厅 + 管线清理完成"
```

#### 方向 C1 — `_pipeline_status()` Step 产出展示增强（~5 行）

**位置：** handler.py L516-520

当前代码：

```python
    for out_step_key, out_info in sorted(step_outputs.items(), key=lambda x: _step_sort_key(x[0])):
        sha = out_info.get("sha", "")[:7]
        desc = out_info.get("output_desc", "")
        if sha or desc:
            lines.append(f"    {out_step_key}: {sha}" + (" — " + desc if desc else ""))
```

改造为：

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

> 注意：`_pipeline_status()` 函数位于 `_cmd_list_workspaces` 内 — 确认修改不会破坏其他显示逻辑。

#### 方向 B3 — 文档清理 + TODO 更新（文档操作）

| 文件 | 操作 | 说明 |
|:-----|:------|:------|
| `docs/README.md` | 更新「最新轮次」→ **R69**；检查内部名残留 | 行 L3 |
| `gateway-plugin/plugin.yaml` | 目视检查：无内部 URL/端口/角色名 | 已确认 ✅ 通用描述 |
| `docs/TODO.md` | v2.33 → v2.34；新增 R69 完成条目 | 见 §3 验收 |

---

| 文件 | 改动 |
|:-----|:------|
| `server/handler.py` | `+step_outputs` 扩展 + `_send_inbox_task` 模板增强 + payload agent_id + `!workspace_reset` + `_infer_artifact_url` + pipeline_status 增强 |
| `docs/README.md` | 更新版本号 |
| `docs/TODO.md` | 版本更新 + R69 条目 |

---

### Step 4 — 🔍 审查（Review）

**主角：** review | **备用：** qa

**审查重点：**
1. ✅ A1: `!step_complete --summary/-s --artifact-url/-u` 参数解析正确
2. ✅ A1: `step_outputs` 含全部必需字段（sha/title/output_desc/summary/artifact_url）
3. ✅ A1: `_infer_artifact_url()` URL 模板正确
4. ✅ A3: `_send_inbox_task` 收件箱消息格式正确，含前序上下文
5. ✅ B1: inbox_payload 含 `agent_id`/`from_agent` 字段
6. ✅ B2: `!workspace_reset` 命令可用，不破坏其他命令
7. ✅ C1: `!pipeline_status` 展示 Step 标题+摘要+URL
8. ✅ Scope 合规：没有引入不在范围内的改动
9. ✅ `grep` 零内部名残留（跨 docs/ + gateway-plugin/ 检查）

---

### Step 5 — 🦐 测试（QA）

**主角：** qa | **备用：** review

**测试项：** 见 §3 验收清单

---

### Step 6 — 🦸 合并部署（Admin）

**主角：** admin | **备用：** arch

**操作：**
- 合并 dev→main
- 部署生产容器
- TODO.md 更新（新增 R69 条目）
- 关闭工作室，恢复大厅

---

## 3. 验收清单

### 🎯 方向 A — 收件箱上下文注入（9 项）

| # | 验收标准 | 预期结果 | 测试方法 |
|:-:|:---------|:---------|:---------|
| ✅-1 | `!step_complete stepN --summary "xxx"` 存入 step_outputs | `pstate.step_outputs[stepN].summary == "xxx"` | 手动调用 → grep _PIPELINE_STATE |
| ✅-2 | `!step_complete stepN --artifact-url "xxx"` 存入 step_outputs | `pstate.step_outputs[stepN].artifact_url == "xxx"` | 手动调用 → 验证 |
| ✅-3 | 不传 `--summary` 时自动降级为 `output_desc` | `summary == step_config.output_desc` | 不带 `-s` 调用 |
| ✅-4 | 不传 `--artifact-url` 时自动推断（step2/4/5）| step2→...R69-tech-plan.md | 不带 `-u` 调用 step2 |
| ✅-5 | 非推断 step（step3/6）不传 artifact_url 时为 `""` | 空字符串 | 不带 `-u` 调用 step3 |
| ✅-6 | step_outputs 含 title/output_desc 字段 | 自动从 step_config 注入 | grep step_outputs |
| ✅-7 | 收件箱消息含前序 Step 的 title + summary + URL | 消息含 `🏗️ 前序 Step 2「xx」✅ (sha)` + `└ 💡` + `└ 🔗` | 启动管线 → 检查 inbox_chat_log |
| ✅-8 | 无前序产出时收件箱消息不崩（降级） | 无 `_prev_section`，直接显示参考文档 | step1 完成后 step2 接收 |
| ✅-9 | summary ≤200 字符截断（软限制） | 超过 200 在渲染时 `.truncate(200)` | 传长字符串 |

### 🎯 方向 B — TODO 清理（5 项）

| # | 验收标准 | 预期结果 | 测试方法 |
|:-:|:---------|:---------|:---------|
| ✅-10 | `_send_inbox_task` 函数签名含 `pm_agent_id` | AST 或 grep 确认 | 代码审查 |
| ✅-11 | inbox_payload JSON 含 `agent_id` 和 `from_agent` | grep handler.py | 代码审查 |
| ✅-12 | `!workspace_reset` 命令注册且可用 | 执行后工作室归档 + 回大厅 + 管线清理 | 启动管线 → 执行命令 → 验证 |
| ✅-13 | docs/README.md 和 gateway-plugin/plugin.yaml 零内部名残留 | `grep -nE '内部'` 零匹配 | 代码审查 |
| ✅-14 | TODO.md 更新 v2.34 + R69 条目 | 版本号 √ + R69 完成条目 | 检查 TODO.md |

### 🎯 方向 C — pipeline_status 增强（2 项）

| # | 验收标准 | 预期结果 | 测试方法 |
|:-:|:---------|:---------|:---------|
| ✅-15 | `!pipeline_status` 展示 Step 标题+摘要+URL | 输出含 `🏗️ 技术方案 — 💡 xxx` + `🔗` | 有产出时执行命令 |
| ✅-16 | summary 较长时截断显示（≤80 字符） | `summary[:80] + "..."` | 传长 summary → 检查 |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — 基于需求文档 v1.0 ✅ |
