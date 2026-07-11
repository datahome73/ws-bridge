# R97 代码审查报告 — AutoRouter 稳定化 🔧

> **审查人：** 🔍 小周
> **审查基准：** `71e9c8b` (R96) → `c7b3844` (R97)
> **改动文件：** `server/auto_router.py` · `server/handler.py` · `server/pipeline_context.py`
> **净变化：** +330/-666 行（-336 净删，架构瘦身）
> **参考文档：** `docs/R97/R97-tech-plan.md` · `docs/R97/R97-product-requirements.md`

---

## 审查结论：🔴 退回

**阻断性问题：角色映射 `_refresh_role_map()` 不处理服务端响应，`_role_index` 恒为空，所有角色解析均失败。**

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:----:|:------|
| 1 | PipelineContext 字段 | 🟢 通过 | StepInfo + ctx 结构完整 |
| 2 | AutoRouter 不依赖 frontmatter | 🟢 通过 | yaml/aiohttp/topology 完全移除 |
| 3 | **角色映射实时查询** | **🔴 退回** | `_refresh_role_map` 只发不接 |
| 4 | 任务消息机械组装 | 🟢 通过 | 纯模板字符串，零 LLM |
| 5 | 向后兼容 | 🟡 条件通过 | `--work_plan_url` 已移除（方案决策） |
| 6 | step1 PM 在链条中 | 🟢 通过 | PM 作为 Step 1 接收任务 |

---

## 1. PipelineContext 字段完整性

**判定：🟢 通过**

### StepInfo dataclass

| 字段 | 类型 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `step_key` | str | `"step1"` ~ `"step6"` | ✅ |
| `role` | str | `"pm"`, `"arch"`, `"dev"`, `"review"`, `"qa"`, `"operations"` | ✅ |
| `title` | str | 步骤标题 | ✅ |
| `status` | str | `"pending"` / `"active"` / `"done"` / `"failed"` / `"skipped"` | ✅ |
| `agent_id` | str | 派活后填充 | ✅ |
| `agent_name` | str | 派活后填充 | ✅ |
| `output` | dict\|None | 完成时 `{"sha": "xxx"}` | ✅ |
| `result_msg` | str | 原始 `✅ 完成` 消息 | ✅ |

### DEFAULT_STEP_ORDER / DEFAULT_STEPS

```python
DEFAULT_STEP_ORDER = ["step1", "step2", "step3", "step4", "step5", "step6"]
DEFAULT_STEPS["step1"] = StepInfo(role="pm", title="标注 WORK_PLAN 已审核")
...
```

6 步缺省链定义清晰，角色齐全。 ✅

### PipelineContextManager 扩展

| 方法 | 用途 | 状态 |
|:-----|:-----|:-----|
| `get_context(round_name)` | 泛型获取（兼容 dict + PipelineContext） | ✅ |
| `set_context(round_name, ctx)` | 直接写入 | ✅ |
| `save()` | 主动持久化 | ✅ |

---

## 2. AutoRouter 不再依赖 frontmatter

**判定：🟢 通过 — 清理彻底**

| 移除项 | 行数 | 状态 |
|:-------|:----:|:------|
| `import yaml` | -1 | ✅ 完全移除 |
| `_STANDARD_PIPELINE_ORDER` | -6 | ✅ 死代码 |
| `_topologies` 缓存 | -4 | ✅ |
| `_pipeline_config` / `_prev_sha` | -3 | ✅ |
| `_fetch_topology()` | ~-60 | ✅ HTTP + YAML 全移除 |
| `_parse_topology()` | ~-50 | ✅ YAML frontmatter 解析 |
| `_render_template()` | ~-20 | ✅ 模板变量替换 |
| `_find_role_in_chain()` | ~-10 | ✅ 用 step_order.index() 替代 |
| `_build_role_index()` | ~-30 | ✅ 替代为实时查询 |
| `aiohttp` 依赖 | — | ✅ 不再需要 |

**新依赖：** `pipeline_contexts.json` 文件 I/O（JSON 序列化/反序列化）

**数据流向：**
```
handler: !pipeline_start → 写入 pipeline_contexts.json
                                    ↓
AutoRouter: 收到 _admin 信号 → 读取 pipeline_contexts.json → 派活
```

---

## 3. 🔴 角色映射实时查询逻辑 (BUG)

**判定：🔴 退回**

### Bug 描述

`_refresh_role_map()` 发送 `!agent_card list` 查询到 `_admin`，但**从未读取和处理响应**。`_role_index` 恒为空，所有角色解析均失败。

### 代码走查

```python
async def _refresh_role_map(self) -> None:
    now = time.time()
    if now - self._last_role_refresh < self._role_map_ttl:
        return                            # TTL 缓存
    if not self.ws:
        return

    try:
        await self.ws.send(json.dumps({   # 发送查询
            "type": "message",
            "channel": "_admin",
            "content": "!agent_card list",
            ...
        }))
        self._last_role_refresh = now      # ✅ 只更新时间戳
        # ❌ 没有接收响应的代码！
        # ❌ 没有解析 agent_card list 返回的代码！
        # ❌ 没有更新 self._role_index 的代码！
    except Exception as e:
        logger.warning(...)
```

### 影响分析

所有调用 `_resolve_agent_by_role()` 的路径都会失败：

```
_on_pipeline_ready()
  └─ _resolve_agent_by_role("pm")
       ├─ _refresh_role_map()      ← 只发不接，_role_index 仍为 {}
       ├─ role in _role_index      ← False（空 dict）
       ├─ for known_role in ...    ← 空循环
       └─ short_map fallback       ← 也检查 _role_index → 全部失败
       └─ return None
  └─ agent_id = None
  └─ "未找到对应 bot" → PM 通知（管线卡死！）
```

**结果：** AutoRouter 启动后无法派活任何 Step，所有轮次通知 PM"未找到对应 bot"。

### 修复方向

需要先发送查询，然后等待并接收响应，解析 `!agent_card list` 的返回内容来构建 `_role_index`。有两种方式：

**方案 A（推荐）：** 退回到 R88 的文件读取方式：
```python
async def _refresh_role_map(self) -> None:
    # 从 Agent Card 文件直接读取（替代 WS 查询）
    path = os.path.join(self.data_dir, "..", "config", "agent_cards.json")
    if os.path.exists(path):
        cards = json.loads(open(path).read())
        # 构建 _role_index ...
    self._last_role_refresh = now
```

**方案 B（纯异步）：** 实现 request-response 模式，发送查询后等待 `_admin` 响应：
```python
# 需要改 _handle_message 增加对 !agent_card list 响应的识别
# 通过 msg_id 关联请求和响应
```

---

## 4. 任务消息机械组装（无 LLM）

**判定：🟢 通过**

```python
def _build_task_message(ctx: dict, step: dict, prev_sha: str) -> str:
    lines = [
        f"【{ctx['round_name']} Step {step['step_key']} 任务 — {step['title']} 🎯】",
        "",
        f"角色: {step['role']}",
        f"前一棒已完成: {prev_sha or '（无）'}",
        "",
        "请按流程完成任务后推 dev 分支。",
        "完成后请回复 _inbox:server 告知 SHA。",
    ]
    return "\\n".join(lines)
```

| 检查项 | 状态 |
|:-------|:-----|
| 纯字符串拼接，无 LLM 调用 | ✅ |
| 无模板变量替换 `${...}` | ✅ |
| 无 aiohttp / HTTP 请求 | ✅ |
| 结果可预测、可测试 | ✅ |

---

## 5. 向后兼容（`--work_plan_url` 参数）

**判定：🟡 条件通过**

| 旧参数 | 状态 | 说明 |
|:-------|:----:|:------|
| `--work_plan_url <url>` | ❌ 移除 | 技术方案明确 R97 为零 frontmatter |
| `--from <step>` | ❌ 移除 | 默认从 step1 开始 |
| `--workspace-id <ws_id>` | ❌ 移除 | 不再创建 workspace |
| `--force` | ❌ 移除 | 不再校验 frontmatter |
| `--mode auto/manual` | ❌ 移除 | 默认全自动 |

**评估：** 这是有意的架构简化（技术方案 §1.1 核心架构变化）。`PipelineContext.work_plan_url` 字段保留在数据结构中但当前无设置入口，可供后续恢复。向下兼容性无损（旧配置仍可通过旧版 server 运行）。评为 🟡 条件通过，提醒文档需同步更新。

---

## 6. Step 1 PM 在链条中的定位

**判定：🟢 通过**

### 变更

| 维度 | R88 旧 | R97 新 |
|:-----|:-------|:-------|
| PM 角色 | 管线外协调者（Step 1 视为已完成的触发者） | Step 1 执行者 |
| 启动方式 | `!pipeline_start` = Step 1 完成 | `!pipeline_start` 触发 Step 1 派活给 PM |
| 消息 | PM 收到通知"管线已启动" | PM 收任务"标注 WORK_PLAN 已审核"并需回复完成 |

### 流程

```
!pipeline_start R97
  ↓ handler._cmd_pipeline_start: 写入 PipelineContext
  ↓ _admin 广播 "🚀 R97 管线已启动"
  ↓ AutoRouter._on_pipeline_ready()
  ↓ 找第一 pending step → step1(pm)
  ↓ _resolve_agent_by_role("pm") → ??? (见 Bug 3)
  ↓ _dispatch_step → PM 收到任务 📥
```

PM 完成 Step 1 后 `✅ 完成` → AutoRouter 推进到 Step 2 → arch。PM 获得明确的"管线段落感"（先完成自己的份额，再等全线闭环）。✅

---

## 额外发现

### _cmd_pipeline_start 大幅瘦身

| 指标 | R96 | R97 |
|:-----|:---:|:---:|
| 行数 | ~350 | ~60 |
| 参数 | 7 个（force/from/workspace-id/mode/work_plan_url） | 1 个（round_name） |
| 外部调用 | `_parse_frontmatter`, `_build_pipeline_config`, `_cmd_create_workspace`, `_cmd_rollcall_next`, `_cmd_task_create`, `_persist_broadcast` | 无 |
| workspace | 创建 + 成员收集 + 邀请 | 完全不创建 |

✅ 干净的重写。

### 旧角色映射残留未清理

`_extract_role()` 方法仍然保留（auto_router.py），但 `_on_step_complete` 不再调用它——现在通过 `step_order` index 匹配完成 Step。属于死代码但无害。

### v. 技术方案一致性

| 方案条目 | 实现 | 状态 |
|:---------|:-----|:-----|
| `StepInfo` + `DEFAULT_STEPS` | `pipeline_context.py` | ✅ |
| `_cmd_pipeline_start` 简化 | `handler.py` ~60 行 | ✅ |
| AutoRouter 从 PipelineContext JSON 读取 | `_load/save_pipeline_context` | ✅ |
| 角色映射实时查询 | `_resolve_agent_by_role` 存在但功能不完整 | 🔴 |
| 任务消息机械组装 | `_build_task_message` | ✅ |
| Step 1 PM 在链条中 | `DEFAULT_STEPS["step1"]` role=pm | ✅ |

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:------|
| PipelineContext 字段 | 🔴 | 🟢 | StepInfo 8 字段完整 |
| AutoRouter 不依赖 frontmatter | 🔴 | 🟢 | yaml/aiohttp/topology 全移除 |
| 角色映射实时查询 | 🔴 | 🔴 | `_refresh_role_map` 只发不接，`_role_index` 恒空 |
| 任务消息机械组装 | 🟡 | 🟢 | 纯模板字符串 |
| 向后兼容 | 🟡 | 🟡 | `--work_plan_url` 已移除（架构决策） |
| Step 1 PM 在链条中 | 🟢 | 🟢 | PM 作为正常 Step 接收任务 |
| 架构瘦身质量 | 🟢 | 🟢 | -336 净删，代码结构清晰 |

**最终结论：🔴 退回** — 两处需修复：

1. **🔴 `_refresh_role_map()` 必须实现响应处理或回退到文件读取** — 当前 `_role_index` 恒为空，所有角色解析失败，AutoRouter 无法派活任何 Step。这是阻断性问题。

2. **🟡 建议:** 使用方案 A（回退到 `config/agent_cards.json` 文件读取）而不是纯异步方案 B，因为后者需要在 `_handle_message` 中增加消息关联逻辑，改动面更大。

修复后可重审，其余 5/6 检查项均已通过。

---

*报告编写: 🔍 小周 · 2026-07-11*
