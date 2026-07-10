# R97 — AutoRouter 稳定化：PipelineContext 驱动，去 frontmatter 依赖 🔧

> **版本：** v1.0（初稿）
> **日期：** 2026-07-11
> **作者：** PM 小谷（基于大宏 R96 复盘讨论）
> **状态：** ⏳ 待审核
> **基线：** R96 后 main latest
> **本轮改动范围：** `server/auto_router.py` + `server/pipeline_context.py` + `server/handler.py`
> **参考：** `docs/R96/R96-product-requirements.md`（R96 复盘结论）

---

## 0. 触发事件 — R88→R96 AutoRouter 全链路复盘

| 轮次 | AutoRouter 结果 | 失败根因 |
|:----:|:---------------|:---------|
| R88 | ✅ 成功（首轮验证） | — |
| R89 | ❌ 降级 inbox | `_send(ws)` 单播不广播 |
| R90 | ❌ 降级 inbox | 同上 |
| R91 | ❌ 降级 inbox | 同上 |
| R92 | 🛠️ 修复 | `_send` → `_broadcast_to_channel` |
| R92-V | ✅ 成功 | 修复后验证通过 |
| R94 | ❌ 降级 inbox | WORK_PLAN 缺 frontmatter → 拓扑解析失败 |
| R95 | ⏭️ 没用 | pipeline_stop 功能轮 |
| R96 | ⏭️ 没用 | 预期 workspace 失败 → 直接切 inbox |

**结论：** AutoRouter 在 R92 信号路径修复后，仅因**外围原因**（frontmatter 缺失、PM 预期失败）停止了工作。AutoRouter 本身没有根本性 bug，但它的**脆弱依赖**需要清理。

---

## 1. 设计思路

### 1.1 核心认知变化

| 旧认知（R88 设计） | 新认知（R97） |
|:------------------|:--------------|
| AutoRouter 从 WORK_PLAN frontmatter 解析 topology | **PipelineContext 是唯一真相源**，AutoRouter 直接读它 |
| topology 写在 YAML 里，LLM 需理解 | **steps 是结构化 JSON**，AutoRouter 不需要 LLM |
| Workspace 成员匹配影响派活 | **Workspace = 时间切片**，无成员概念，不影响派活 |
| `!pipeline_start` 依赖 frontmatter 完整性 | `!pipeline_start` 创建 PipelineContext，不依赖 frontmatter |
| 任务消息需拼接上下文 | **从 context 组装**，机械拼接不靠 LLM |

### 1.2 新数据流

```
PM                              Server                              AutoRouter
│                                │                                    │
│① !pipeline_start R97          │                                    │
│   (不需要 --work_plan_url)     │                                    │
│                                │                                    │
│                                ├─② 创建 PipelineContext             │
│                                │   {round, steps, role_map, refs}   │
│                                │                                    │
│                                ├─③ _broadcast_to_channel(ADMIN)     │
│                                │   "R97 管线已启动 + context_id"    │
│                                │                                    │
│                                │←─── ④ AutoRouter 收到广播 ───────┤
│                                │     读 PipelineContext             │
│                                │     "step2=active, role=arch"      │
│                                │                                    │
│                                ├─⑤ _inbox:ws_3f7c... → arch        │
│                                │   "Step 2: 技术方案"               │
│                                │                                    │
│                                │←─── ⑥ ✅ 完成 ──────────────────┤
│                                │     更新 PipelineContext            │
│                                │     step2=done → step3=active      │
│                                │                                    │
│                                ├─⑦ _inbox:ws_0bb7... → dev         │
│                                │   "Step 3: 编码"                   │
│                                │   ... chain 继续到 step6           │
│                                │                                    │
│←── 🏁 全部完成 ───────────────┤                                    │
```

**关键变化：**
- `!pipeline_start` 不再需要 `--work_plan_url` 参数（可省略，URL 可选放在 refs 里）
- PipelineContext 在 server 端创建并持久化，AutoRouter 通过 WS 读取
- 任务消息从 context 机械组装，不涉及 LLM 解析

---

## 2. PipelineContext 结构化设计

### 2.1 数据结构

```python
@dataclass
class PipelineContext:
    round_name: str                    # "R97"
    status: str                        # "running" | "stopped" | "done"
    created_at: float
    triggerer_id: str                  # 发起者 agent_id

    # Step 链
    steps: dict[str, StepInfo]         # {"step2": StepInfo, ...}
    step_order: list[str]              # ["step2", "step3", "step4", "step5", "step6"]

    # 角色到 agent 的映射
    role_agent_map: dict[str, str]     # {"arch": "ws_3f7c...", "dev": "ws_0bb7..."}

    # 参考资料（可选，bot 自取）
    references: dict[str, str]         # {"work_plan": "https://...", "requirements": "https://..."}


@dataclass
class StepInfo:
    role: str                          # "arch", "dev", "review", "qa", "operations"
    status: str                        # "pending" | "active" | "done" | "failed" | "skipped"
    agent_id: str                      # 执行者 agent_id
    agent_name: str                    # 执行者 display_name（小开、爱泰…）
    output: dict | None = None         # {"sha": "...", "summary": "...", "artifact_url": "..."}
```

### 2.2 默认 Step 链

```python
DEFAULT_PIPELINE_STEPS = {
    "step2":  StepInfo("arch",        "pending", ...),
    "step3":  StepInfo("dev",         "pending", ...),
    "step4":  StepInfo("review",      "pending", ...),
    "step5":  StepInfo("qa",          "pending", ...),
    "step6":  StepInfo("operations",  "pending", ...),
}
DEFAULT_STEP_ORDER = ["step2", "step3", "step4", "step5", "step6"]
```

### 2.3 角色到 agent 的映射

AutoRouter 从 Agent Card 的 `pipeline_roles` 实时查询角色→agent_id 映射：

```python
def _resolve_agent_by_role(self, role: str) -> str | None:
    """从 Agent Card 查询 role 对应的 agent_id。"""
    cards = self._query_agent_cards()
    for aid, card in cards.items():
        if role in card.get("pipeline_roles", []):
            return aid
    return None  # → 通知 PM 补充角色
```

**优势：** 加新人（如晓周）自动纳入角色池，不需要改任何配置。

---

## 3. 功能详细描述

### 3.1 `!pipeline_start` 简化

| 当前（R88-R96） | R97 |
|:----------------|:-----|
| `!pipeline_start R97 --work_plan_url <url>` | `!pipeline_start R97` |
| 依赖 frontmatter 解析 topology | **零依赖**，用默认 Step 链 |

可选参数（仅当需要附加参考 URL 时）：

```
!pipeline_start R97 --work_plan_url <url> --requirements_url <url>
```

**创建 PipelineContext 的流程：**

```python
async def _cmd_pipeline_start(sender_id, params):
    round_name = params["_positional"][0]

    # 1. 构建角色映射（从 Agent Card 实时查询）
    role_map = {}
    for role in DEFAULT_ROLES:  # ["arch","dev","review","qa","operations"]
        aid = _resolve_role_agent(role)
        if aid:
            role_map[role] = aid

    # 2. 构建 Step 链
    steps = {}
    for step_key in DEFAULT_STEP_ORDER:
        role = STEP_ROLE_MAP[step_key]
        steps[step_key] = StepInfo(
            role=role,
            status="active" if step_key == DEFAULT_STEP_ORDER[0] else "pending",
            agent_id=role_map.get(role, ""),
            agent_name=_get_agent_name(role_map.get(role, "")),
        )

    # 3. 创建并持久化 PipelineContext
    ctx = PipelineContext(
        round_name=round_name,
        status="running",
        created_at=time.time(),
        triggerer_id=sender_id,
        steps=steps,
        step_order=DEFAULT_STEP_ORDER,
        role_agent_map=role_map,
        references={},  # optional, from --work_plan_url/--requirements_url
    )
    _pipeline_manager.save_context(round_name, ctx)

    # 4. 广播到 _admin（AutoRouter 监听）
    await _broadcast_to_channel(ADMIN_CHANNEL, {
        "type": "broadcast", "channel": ADMIN_CHANNEL,
        "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
        "content": f"🚀 R97 管线已启动 — context_id={round_name}",
    })
```

### 3.2 AutoRouter 重构

**旧行为（R88）：**
1. 监听 PM inbox + _admin
2. `_on_pipeline_ready()` → HTTP GET WORK_PLAN raw URL → 解析 YAML frontmatter → 构建 topology
3. `_dispatch_step()` → 拼装任务消息 → 发 inbox
4. `_on_step_complete()` → 检测 `✅ 完成` → 提取 SHA/role → 匹配 topology → 下一棒

**新行为（R97）：**
1. 监听 _admin 频道（`"管线已启动"` 信号）
2. `_on_pipeline_ready()` → 从 `_pipeline_manager.get_context(round_name)` 读取 PipelineContext
3. `_dispatch_step()` → 从 context 读 step 角色+agent_id → 机械组装任务消息 → 发 inbox
4. `_on_step_complete()` → 检测 `✅ 完成` → 提取 SHA → **更新 PipelineContext**（stepN=done, stepN+1=active） → 发下一棒

```python
# AutoRouter 新版核心逻辑
class PipelineAutoRouter:
    async def _handle_message(self, msg):
        content = msg.get("content", "")
        channel = msg.get("channel", "")

        # 只关心 _admin 频道的管线信号
        if channel != "_admin":
            return

        if "管线已启动" in content:
            round_name = self._extract_round(content)
            await self._on_pipeline_ready(round_name)
        elif "✅ 完成" in content:
            await self._on_step_complete(content)

    async def _on_pipeline_ready(self, round_name):
        # 读取 PipelineContext（不从 WORK_PLAN 解析！）
        ctx = self._pipeline_manager.get_context(round_name)
        if not ctx or ctx.status != "running":
            return

        # 找第一个 active 的 step
        for step_key in ctx.step_order:
            step = ctx.steps[step_key]
            if step.status == "active":
                await self._dispatch_step(ctx, step_key)
                break

    async def _dispatch_step(self, ctx, step_key):
        step = ctx.steps[step_key]
        # 机械组装任务消息
        task = self._build_task_message(ctx, step_key)
        await self._send_inbox(step.agent_id, task)
        self._step_dispatch_times[ctx.round_name][step_key] = time.time()

    def _build_task_message(self, ctx, step_key):
        step = ctx.steps[step_key]
        prev_step = self._get_prev_step(ctx, step_key)

        lines = [f"【{ctx.round_name} {step_key} 任务 — {step.role}】"]
        if prev_step and prev_step.output:
            lines.append(f"前一棒已完成: {prev_step.output.get('sha', '?')}")
            lines.append(f"摘要: {prev_step.output.get('summary', '')}")
        lines.append(f"角色: {step.agent_name} ({step.agent_id[:12]})")
        if ctx.references.get("work_plan"):
            lines.append(f"参考: {ctx.references['work_plan']}")
        if ctx.references.get("requirements"):
            lines.append(f"需求: {ctx.references['requirements']}")
        lines.append("完成后推 dev。")
        lines.append(f"**完成后请回复 _inbox:{ctx.triggerer_id} 告知 SHA。**")
        return "\n".join(lines)

    async def _on_step_complete(self, content):
        round_name = self._extract_round(content)
        sha = self._extract_sha(content)
        role = self._extract_role(content)

        ctx = self._pipeline_manager.get_context(round_name)
        if not ctx:
            return

        # 找到对应 role 的 step，标为 done
        for step_key in ctx.step_order:
            if ctx.steps[step_key].role == role and ctx.steps[step_key].status == "active":
                ctx.steps[step_key].status = "done"
                ctx.steps[step_key].output = {"sha": sha, "summary": "", "artifact_url": ""}
                break

        # 激活下一 step
        next_key = self._get_next_step(ctx, step_key)
        if next_key:
            ctx.steps[next_key].status = "active"
            ctx.role_agent_map = self._refresh_role_map()  # 重新查询角色映射
            await self._dispatch_step(ctx, next_key)
        else:
            # 全部完成
            ctx.status = "done"
            await self._send_to_pm(f"🏁 {round_name} 全部 Step 已完成！")

        # 持久化更新
        self._pipeline_manager.save_context(round_name, ctx)
```

### 3.3 任务消息模板

结构化组装，不依赖 LLM：

```python
TASK_TEMPLATE = """\
【{round_name} {step_key} 任务 — {role_name} 🎯】

角色: {agent_name}
{prev_info}
参考: {refs}

完成后推 dev。
**完成后请回复 _inbox:{pm_id} 告知 SHA。**
"""
```

变量都是机械替换——`round_name`, `step_key`, `role_name`, `agent_name`, `prev_info`, `refs`, `pm_id`。不涉及 LLM 理解或拼接。

### 3.4 角色映射自动刷新

每次派活前，AutoRouter 重新查询 Agent Card 的 `pipeline_roles` 映射。这样：

| 场景 | 效果 |
|:-----|:------|
| 晓周注册为新 reviewer | 自动纳入 `review` 角色池，无需改配置 |
| 小周忙不过来 | 晓周自动作为备选（如果 role_map 有多 agent） |
| bot 角色变更 | 重新 `agent_card_register` 后下一轮自动生效 |

**角色选择策略（多 agent 同角色时）：**

```python
def _pick_agent_for_role(self, role, candidates):
    """多候选时轮询/随机选一个。"""
    # 简单策略：圈中谁用谁（后续可加负载均衡）
    return random.choice(candidates)
```

pm 角色固定为触发者，不走轮询。

---

## 4. 与现有系统的兼容

### 4.1 向后兼容

| 旧行为 | R97 新行为 | 兼容 |
|:-------|:----------|:----:|
| `!pipeline_start R97 --work_plan_url <url>` | 仅 `!pipeline_start R97` 即可 | 🟢 `--work_plan_url` 仍支持（存 refs 里） |
| WORK_PLAN frontmatter 解析 topology | 从 PipelineContext 读 steps | 🟢 旧 frontmatter 被忽略但无害 |
| Workspace 成员匹配 | 不创建 workspace（仅时间切片） | 🟢 向后兼容—`!create_workspace` 命令仍可用 |
| `_PIPELINE_CONFIG` 全局变量 | PipelineContextManager 统一管理 | 🟢 已有 R77 的 PipelineContextManager |

### 4.2 不在此轮改动的

| 事项 | 原因 |
|:-----|:------|
| `!pipeline_stop` 命令 | ✅ R95 已实现，无需改动 |
| 工作室管理命令 | 保留，但 AutoRouter 不再依赖它 |
| Web 端 Pipeline 可视化 | 非核心功能 |
| 超时检测 + 告警 | ✅ R89 已实现，只需适配新 context |

---

## 5. 验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `!pipeline_start R97` 零参数成功 | 只输入轮次名，不需要任何 URL 参数 |
| 2 | PipelineContext 创建并持久化 | `_pipeline_manager.get_context("R97")` 返回完整结构 |
| 3 | AutoRouter 收到信号后自动派活 step2→arch | arch inbox 出现 Step 2 任务消息 |
| 4 | 任务消息中包含前一棒 SHA 引用（如有） | 消息格式含 `前一棒已完成: xxxxxx` |
| 5 | arch 完成回复后 AutoRouter 自动派活 step3→dev | dev inbox 出现 Step 3 任务 |
| 6 | 晓周自动纳入 reviewer 角色池 | 无需任何配置，`!agent_card list` 有晓周即可 |
| 7 | 全链 6 Step 自动走完 | PM 收到 `🏁 R97 全部 Step 已完成！` |
| 8 | 中途不切 inbox（纯自动） | 全程无 PM 手动派活记录 |
| 9 | `--work_plan_url` 参数仍兼容 | 带参数启动，URL 出现在 refs 中 |

---

## 6. 改动文件清单

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `server/pipeline_context.py` | ~+50 行 | StepInfo dataclass + DEFAULT_PIPELINE_STEPS + 角色解析函数 |
| `server/handler.py` | ~+30/-20 行 | `_cmd_pipeline_start` 简化：创建 PipelineContext 替代 frontmatter 解析 |
| `server/auto_router.py` | **~+200/-150 行** | 核心重构：从 PipelineContext 读取拓扑，替代 HTTP GET + YAML 解析 |
| | **合计** | **~+280/-170 = 净增 ~110 行** |

---

## 7. 风险与缓解

| 风险 | 缓解 |
|:-----|:------|
| AutoRouter 重构引入新 bug | 旧代码全重写，核心逻辑变简单（读 context → 发 inbox → 等回复） |
| 角色映射动态查询增加延迟 | 缓存 60s，`_refresh_role_map()` 每次派活前调一次 |
| `!pipeline_start` 不传 URL 时 bot 不知参考文档 | Bot 通过 `!pipeline_status` 获取 refs URL，或 PM 通过 `--work_plan_url` 传入 |
| 多 agent 同角色时选错人 | 简单随机策略，后续可升级为负载均衡/轮询 |
