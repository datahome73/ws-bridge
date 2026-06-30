# R48 技术方案 — 管线通用化 + 完成通知闭环

> **版本：** v0.1
> **状态：** 📝 初稿
> **编制人：** 🏗️ 架构师
> **日期：** 2026-06-28
> **基于需求：** [R48-product-requirements.md v0.2 ✅](./R48-product-requirements.md)
> **基于计划：** [WORK_PLAN.md v0.1](./WORK_PLAN.md)
> **改动范围：** 仅 `server/handler.py`（零改动 config.py / __main__.py）

---

## 目录

1. [方向 A — 通用化 Work Plan URL](#方向-a--通用化-work-plan-url)
2. [方向 B — 管线完成通知闭环](#方向-b--管线完成通知闭环)
3. [改动清单](#改动清单)
4. [向后兼容性分析](#向后兼容性分析)
5. [风险与注意事项](#风险与注意事项)

---

## 方向 A — 通用化 Work Plan URL

### A.1 参数解析（`_cmd_pipeline_start`）

**输入参数：** `!pipeline_start <项目名> --work-plan-url <URL> --from step2`

`--work-plan-url` 通过 `params.get("work_plan_url", "")` 提取（与 `--from` 同模式，框架自动解析 `--key value`）。

```
!pipeline_start R48 --from step2
                ↑ positional[0]    ↑ params["from"]
!pipeline_start chiangmai --work-plan-url https://... --from step2
                ↑ positional[0]    ↑ params["work_plan_url"]    ↑ params["from"]
```

### A.2 流程修改（`_cmd_pipeline_start`，≈行 1092-1108）

**当前逻辑**（R47）：
```python
# 硬编码拼接，只能用于 ws-bridge Round
_remote_url = f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/WORK_PLAN.md"
# HEAD 验证 → 本地 fallback → 报错
```

**目标逻辑**（R48）：
```
work_plan_url = params.get("work_plan_url", "")
if work_plan_url:
    # ① HEAD 请求验证远程 URL 可达
    # ② 失败 → 返回 "❌ WORK_PLAN URL 不可达"
    # ③ 成功 → 跳过原本的拼接验证
else:
    # 走现有逻辑：config.WORK_PLAN_REPO_URL + round_name 拼接
    # HEAD 验证 → 本地 fallback → 报错（完全不变）
```

**删除/替换：** 将原有 17 行验证块（≈行 1092-1108）替换为带条件分支的新块。新增约 15 行，无删除净代码。

### A.3 管线状态存储

`_set_pipeline_state` 调用新增两个字段（≈行 1163-1168）：

```python
_set_pipeline_state(round_name, {
    "active": True,
    "current_step": start_step,
    "ws_id": ws_id,
    "started_at": time.time(),
    "work_plan_url": work_plan_url or None,   # 方向 A: 传入的 URL
    "triggerer_id": sender_id,                 # 方向 B: 触发者 ID
})
```

### A.4 Step 2 点名上下文（≈行 1145-1153）

**当前：**
```python
context_urls = (
    f"需求: docs/{round_name}/{round_name}-product-requirements.md | "
    f"WORK_PLAN: docs/{round_name}/WORK_PLAN.md"
)
```

**目标：**
```python
if work_plan_url:
    context_summary = f"WORK_PLAN: {work_plan_url}"
else:
    context_summary = (
        f"需求: docs/{round_name}/{round_name}-product-requirements.md | "
        f"WORK_PLAN: docs/{round_name}/WORK_PLAN.md"
    )
```

> **设计选择：** 有自定义 URL 时只传 WORK_PLAN 链接（需求文档链接已在策划阶段嵌入 WORK_PLAN 内部，符合需求 §6.1 说明）。无自定义 URL 时保留原格式保持向后兼容。

### A.5 验收覆盖

| 验收标准 | 实现要点 |
|:--------|:---------|
| **A-1** `--work-plan-url` 验证远程 URL | §A.2 条件分支：HEAD 请求查验 |
| **A-2** 未传时走默认拼接 | §A.2 else 分支，代码不变 |
| **A-3** Step 2 上下文传递 URL | §A.4 条件构建上下文 |
| **A-4** URL 存入管线状态 | §A.3 `_PIPELINE_STATE[round_name]["work_plan_url"]` |
| **A-5** HEAD 失败返回错误提示 | §A.2 分支返回 "❌ WORK_PLAN URL 不可达" |
| **A-6** `!pipeline_status` 展示 work_plan_url | §A.6 `_cmd_pipeline_status` 扩展 |
| **A-7** 向后兼容 | §A.2 无 `--work-plan-url` 时行为完全不变 |

### A.6 `!pipeline_status` 展示增强（≈行 1307-1343）

扩展 `_cmd_pipeline_status`，在管线标题行下方展示 `work_plan_url`（如有）：

```python
if pstate.get("work_plan_url"):
    lines.append(f"  📎 WORK_PLAN: {pstate['work_plan_url']}")
```

新增 4 行（1 行判断 + 1 行 append + 2 行空行）。

---

## 方向 B — 管线完成通知闭环

### B.1 触发者记录（`_cmd_pipeline_start`）

已在 §A.3 中合并处理：`_set_pipeline_state` 新增 `"triggerer_id": sender_id`。

`sender_id` 即调用 `!pipeline_start` 的 WebSocket 连接的 `agent_id`（如 `qiubot`、`xiao-ai`）。

### B.2 最后一步 → 写入 `_admin` 频道（`_cmd_step_complete`，≈行 1234-1245）

**当前**（最后一步分支）：
```python
close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
if "❌" in str(close_result):
    return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
set_lobby_paused(False)
_clear_pipeline_state(round_name)
return (
    f"🏁 **{round_name} 管线已完成！**\n"
    f"  {task_result}\n"
    f"  工作室已关闭，大厅已恢复接收"
)
```

问题：管线状态在 `_clear_pipeline_state` 中被清除，此时 `triggerer_id` 已丢失。`--output` 参数值也未在返回信息中展示。

**目标**：在关闭工作区和清除状态之前，先提取所需信息并写入 `_admin` 频道：

```python
# 最后一步 → 管线结束（在关闭之前提取状态信息）
triggerer_id = _PIPELINE_STATE.get(round_name, {}).get("triggerer_id", "")

close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
if "❌" in str(close_result):
    return f"❌ 管线关闭失败，请手动处理：\n{close_result}"

set_lobby_paused(False)

# ── R48 B: 写入 _admin 频道完结通知 ──
try:
    admin_channel = p.ADMIN_CHANNEL
    cleanup_msg = (
        f"🔔 [PIPELINE_COMPLETE] {round_name} — 所有 Step 已完结 ✅\n"
        f"最终产出: {output_ref}\n"
        f"工作室已关闭，大厅已恢复接收"
    )
    ms.save_message(
        msg_id=str(uuid.uuid4()), msg_type="broadcast",
        from_agent="系统", from_name="系统",
        content=cleanup_msg, ts=time.time(),
        data_dir=config.DATA_DIR, channel=admin_channel,
    )
    write_chat_log("系统", cleanup_msg, channel=admin_channel)
except Exception:
    pass
# ── R48 B: End ──

_clear_pipeline_state(round_name)
return (
    f"🏁 **{round_name} 管线已完成！**\n"
    f"  🎯 产出: {output_ref}\n"
    f"  {task_result}\n"
    f"  工作室已关闭，大厅已恢复接收"
)
```

### B.3 消息格式

`_admin` 频道收到的消息：
```
🔔 [PIPELINE_COMPLETE] R48 — 所有 Step 已完结 ✅
最终产出: merge:abc1234
工作室已关闭，大厅已恢复接收
```

PM 看到后：
> 🔔 R48 管线已完成！✅
> 工作室已关闭，大厅已恢复接收
> 最终产出：merge:abc1234
> 下一轮开发可以提需求了。

### B.4 中间 Step 的 `_admin` 通知（≈行 1276-1290）

**不变。** 中间 Step 继续使用 `📋 R48 进度：Step3 ✅ → 下一棒 开发工程师（Step4）产出: abc1234` 格式。

仅最后一步（current_idx is None 分支）从「无通知」升级为「🔔 [PIPELINE_COMPLETE]」。

### B.5 验收覆盖

| 验收标准 | 实现要点 |
|:--------|:---------|
| **B-1** 最后一步写入 🔔 完结消息 | §B.2 `ms.save_message()` + `write_chat_log()` to `_admin` |
| **B-2** 消息含管线名 + 产出 + 关闭信息 | §B.3 消息模板 |
| **B-3** 记录 `triggerer_id` | §A.3 `_set_pipeline_state` 扩展 |
| **B-4** 中间 Step 通知不变 | §B.4 零改动 |
| **B-5** 端到端验证 | 见测试方案 |

---

## 改动清单

| # | 文件 | 函数 | 位置 | 改动类型 | 预估行数 |
|:-:|:----|:-----|:-----|:---------|:--------:|
| 1 | `handler.py` | `_cmd_pipeline_start` | ≈行 1092-1108 | 替换为条件分支（URL 参数解析 + HEAD 验证） | ~+15 |
| 2 | `handler.py` | `_cmd_pipeline_start` | ≈行 1145-1153 | 条件构建 Step 2 上下文 URL | ~+5 |
| 3 | `handler.py` | `_cmd_pipeline_start` | ≈行 1162-1168 | 管线状态新增 `work_plan_url` + `triggerer_id` | ~+2 |
| 4 | `handler.py` | `_cmd_step_complete` | ≈行 1234-1245 | 最后一步分支：提取 triggerer_id + 写入 `_admin` 完结通知 | ~+15 |
| 5 | `handler.py` | `_cmd_step_complete` | ≈行 1241-1245 | 最后一步返回消息加入 `--output` 值 | ~+1 |
| 6 | `handler.py` | `_cmd_pipeline_status` | ≈行 1315-1320 | 展示 work_plan_url（如有） | ~+4 |
| | | | | **合计** | **~+42** |

**净新增 ≈42 行，零删除，零改动其他文件。**

---

## 向后兼容性分析

| 场景 | R47 行为 | R48 行为 | 兼容？ |
|:-----|:---------|:---------|:------:|
| `!pipeline_start R49 --from step2` | HEAD 验证远程 + 本地 fallback | 同左（走 else 分支） | ✅ 完全一致 |
| `!pipeline_start R49 --from step2` 后 `!pipeline_status` | 无 work_plan_url 行 | 无 work_plan_url 行（字段为 None → 跳过） | ✅ 输出一致 |
| `!step_complete Step5`（中间 Step） | `📋` 通知 `_admin` | `📋` 通知 `_admin`（不变） | ✅ 完全一致 |
| `!step_complete Step6`（最后一步） | 仅 `🏁` 返回（无 `_admin` 通知） | `🏁` 返回 + `🔔 [PIPELINE_COMPLETE]` 到 `_admin` | ✅ 增强，不破坏现有 |
| 管线最后一步产出未展示 | 无 `--output` 展示 | 新增 `🎯 产出:` 行 | ✅ 只增不减 |

**结论：** 所有 P0 向后兼容验收标准（A-2, A-7）满足。未传 `--work-plan-url` 时 0 行为变化。

---

## 风险与注意事项

### R1. `_clear_pipeline_state` 时机

必须在写入 `_admin` 通知之后调用，否则 `triggerer_id` 丢失。§B.2 的设计已正确处理：先提取 `triggerer_id` 到局部变量 → 关闭工作室 → 写入通知 → 清理状态。

### R2. HEAD 请求超时

`--work-plan-url` 的 HEAD 验证复用现有 R45 模式的 5 秒超时（`urlopen(..., timeout=5)`）。如果 URL 指向慢速服务器或私有网络，可能误判为不可达。建议保持 5 秒超时，不做调整——用户如果发现超时可重试或确认 URL 正确性。

### R3. 命令行格式一致性

`--work-plan-url` 的参数名使用下划线而非连字符，与现有 `--from` 参数风格一致（均为 params dict 的 snake_case key）。框架解析 `--work-plan-url https://...` 时自动映射为 `params["work_plan_url"]`。

### R4. 不处理鉴权

HEAD 请求不携带任何 Cookie / Authorization header。如果 URL 指向需要鉴权的资源（私有仓库、Google Docs），请求会失败并返回「❌ WORK_PLAN URL 不可达」。这与需求文档 §5 一致——本轮只处理公开可访问链接。

---

## 参考

- R45 WORK_PLAN_REPO_URL 远程验证模式（`references/r45-work-plan-remote-url-pattern.md`）
- `server/handler.py` `_cmd_pipeline_start` 行 1081-1177（R47 基线）
- `server/handler.py` `_cmd_step_complete` 行 1180-1304（R47 基线）
- `server/handler.py` `_cmd_pipeline_status` 行 1307-1343（R47 基线）
