# R88 产品需求 — 管线自动路由：Pipeline AutoRouter 🚂

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R87 `_inbox:server` 中继架构已部署 ✅ | 所有 bot 已适配 `_inbox:server` 回复协议 ✅

---

## 1. 问题背景

### 1.1 现状

R87 已完成 `_inbox:server` 中继架构，当前通信流：

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ───────── _inbox:<bot_id> ─→│─────────────────────────────────→│
│                                  │                                  │
│                                  │←── ② ACK ✅ R{轮次} 收到！─────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK ──────────────────┤                                  │
│                                  │         [bot 干活中...]         │
│                                  │←── ④ ✅ 完成 ──────────────────┤
│←── ⑤ 转发 完成 ────────────────┤                                  │
│                                  │── ⑥ 自动确认 ── _inbox:<bot_id>─→│
│                                  │                                  │
│  PM 此时仍需手动发送下一棒的派活 ←──────── 无自动接力 ──────────────│
```

**PM 仍需手动做的工作：** 收到 bot 的完成通知后，给下一个 Step 的 bot 发派活消息。R87 解决了 bot→server→PM 的自动转发，但 Step 之间的**任务接力仍需 PM 手动完成**。

### 1.2 暴露的问题

| # | 问题 | 影响 | 频次 |
|:-:|:-----|:------|:----:|
| 🔴 | **每完成一个 Step，PM 都要手动发下一棒任务** | PM 必须在线监听、手动转发，无法真正「一次派活、全线自动」 | 每 Step 1 次 |
| 🟡 | **多 bot 并行工作时，PM 需维护 Step 顺序状态** | 多个 bot 的完成消息交叉到达，PM 需记住当前到哪一步了 | 轮次 × bot 数 |
| 🟢 | **Step 6 自动确认的文案仍是「本轮任务完成」** | R87 的自动确认没有区分「已完成 Step」和「全部完成」 | 每完成消息 1 次 |

### 1.3 目标

> **R88 目标：引入 Pipeline Topology + AutoRouter，让 server 在接收到 `✅ 完成` 时自动读取管线拓扑、找到下一棒 bot、自动派发下一 Step 任务。PM 只需派活第 1 条消息，后续全线自动接力。** 🚂

---

## 2. 方案设计

### 2.1 核心架构

**新增概念：Pipeline Topology（管线拓扑）**

管线拓扑定义了：
- Step 之间的前后依赖关系（Step N → Step N+1）
- 每个 Step 的负责人（使用 role 映射到 agent_id）
- 每个 Step 的任务模板（可继承 frontmatter 中定义的 context）

### 2.2 通信流（R88 后）

```
PM                                Server                              Bot A
│                                  │                                  │
│① 派活 Step 2 ── _inbox:botA ──→│─────────────────────────────────→│
│   PM 仅发 1 条消息               │                                  │
│                                  │                                  │
│                                  │←── ② ACK ✅ R88 收到！────────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK ──────────────────┤                                  │
│                                  │                                  │
│                                  │         [Bot A 干活中...]       │
│                                  │                                  │
│                                  │←── ④ ✅ 完成 ─────────────────┤
│                                  │     (_inbox:server)              │
│←── ⑤a 转发 完成 ──────────────┤                                  │
│                                  │── ⑤b 自动确认 Bot A ──────────→│
│                                  │    (_inbox:botA)                 │
│                                  │                                  │
│                                  │── ⑥ 自动派活 Bot B ←── 🆕     │
│                                  │    (_inbox:botB)                 │
│                                  │    "Step 3 任务：编码实现"       │
│                                  │         [Bot B 干活中...]       │
│                                  │                                  │
│                                  │←── ⑦ ACK ✅ / ✅ 完成 ───────┤
│                                  │                                  │
```

**PM 视角：派活 1 条 → 后台干活 → 收全部通知。全程零手动接力。**

### 2.3 三步演进

| 阶段 | 内容 | 状态 |
|:----:|:-----|:----:|
| **Phase A** | 管线拓扑定义（frontmatter 扩展） | ✅ **R88 实现** |
| **Phase B** | AutoRouter + 自动派活 | ✅ **R88 实现** |
| **Phase C** | 全流程测试验证 | ✅ **R88 验证** |

### 2.4 关键设计原则

| # | 原则 | 说明 |
|:-:|:-----|:------|
| 1 | **不引入新持久化状态** | Pipeline Topology 直接从 `_PIPELINE_CONFIG`（frontmatter 解析）读取，不新增状态表 |
| 2 | **不改变 `_inbox:server` 协议** | Bot 的回复协议完全不变（ACK ✅ / ✅ 完成），AutoRouter 是 **server 侧新增行为** |
| 3 | **向后兼容** | 无 Pipeline Topology 定义的管线照常运行（PM 手动接力）— 拓扑是可选项 |
| 4 | **拓扑配置即代码** | 前端在 WORK_PLAN frontmatter 中声明拓扑，server 部署时自动解析 |
| 5 | **PM 安全守卫** | PM 对谁发、发什么有完全控制权——AutoRouter 只在 `✅ 完成` 且管线活跃时触发 |
| 6 | **`!pipeline_status` 增强** | AutoRouter 触发后更新管线状态展示，PM 可随时查看进度 |

---

## 3. 实现方案

### 3.1 Pipeline Topology 定义

#### 3.1.1 WORK_PLAN frontmatter 扩展

在现有 `pipeline.steps` 结构中增加 `topology` 字段，定义 Step 之间的自动接力关系：

```yaml
pipeline:
  name: "R88 Pipeline AutoRouter"
  work_plan_url: "..."

  topology:                              # ← 🆕 管线拓扑定义
    start_step: step2                    # 起始 Step（PM 派活此 Step）
    auto_chain: true                     # 是否启用自动接力
    steps:
      step2:
        next: step3                      # Step 2 完成后 → 自动派活 Step 3
        task_template: |
          【{next_round} Step {next_name} 任务 — {next_title} 🎯】

          角色: {next_role}
          前一棒 {prev_role} 已完成 ✅ `{prev_sha}`

          {next_context}

          完成后请回复 _inbox:server 告知 SHA。
      step3:
        next: step4
        task_template: |
          ...
      step4:
        next: step5
      step5:
        next: step6
      step6:
        next: null                        # 终点 Step，无下一棒 → 发送「全部完成通知」给 PM

  steps:
    step2:
      role: architect
      title: 技术方案
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
      artifact_url: "docs/{round}/{round}-tech-plan.md"

    step3:
      role: developer
      title: 编码实现
      context:
        requirements_url: "${pipeline.requirements_url}"
        tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      artifact_url: "（默认 git commit）"

    step4:
      role: reviewer
      title: 代码审查
      context:
        tech_plan_url: "docs/{round}/{round}-tech-plan.md"
        requirements_url: "${pipeline.requirements_url}"
      artifact_url: "docs/{round}/{round}-code-review.md"

    step5:
      role: qa
      title: 测试验证
      context:
        requirements_url: "${pipeline.requirements_url}"
        code_review_url: "docs/{round}/{round}-code-review.md"
      artifact_url: "docs/{round}/{round}-test-report.md"

    step6:
      role: operations
      title: 合并部署归档
      context:
        requirements_url: "${pipeline.requirements_url}"
        test_report_url: "docs/{round}/{round}-test-report.md"
      artifact_url: "（部署确认）"
```

#### 3.1.2 简写格式（最小配置）

对于标准 6-Step 管线，支持省略 `topology` 字段，使用默认拓扑：

```yaml
pipeline:
  name: "R88 Demo"
  auto_chain: true                       # ← 仅需 1 行，启用默认 6-Step 自动接力
  steps:
    step2:
      role: architect
      ...
    step3:
      role: developer
      ...
```

默认拓扑规则：step2→step3→step4→step5→step6（线性），step6 为终点。

#### 3.1.3 Task Template 变量替换

| 变量 | 来源 | 说明 |
|:-----|:-----|:------|
| `{next_round}` | pipeline.name / round_name | 当前轮次 |
| `{next_step}` | 当前拓扑的 next | 下一 Step 的 key（如 step3） |
| `{next_name}` | 拓扑 steps.{next}.title | 下一 Step 的标题 |
| `{next_title}` | 拓扑 steps.{next}.title | 下一 Step 的标题 |
| `{next_role}` | 拓扑 steps.{next}.role | 下一 Step 的角色 |
| `{next_context}` | 拓扑 steps.{next}.context 拼接 | 下一 Step 的上下文 |
| `{prev_role}` | 当前完成 Step 的 role | 前一棒角色 |
| `{prev_sha}` | 从 `✅ 完成` 消息提取的 SHA | 前一棒的产出 |
| `{prev_artifact_url}` | 当前 Step 的 artifact_url | 前一棒的产出文档 URL |

#### 3.1.4 上下文注入规则

AutoRouter 生成的任务消息中，上下文来源优先级（从高到低）：

1. **`task_template` 中手动书写的引用** — 精确控制上下文
2. **`steps.{step}.context` 中定义的 URL/引用** — 自动注入到模板的 `{next_context}`
3. **`_infer_artifact_url()` 自动推断** — 无明确定义时按 Step 类型推断

**SHA 提取规则：** 从 `✅ 完成` 消息中提取 7 位 commit SHA（跟在 `✅ 完成，已推 dev: ` 或 `✅ 完成，commit ` 后）。提取算法同现有 `_extract_sha_from_content()`。

### 3.2 Server 端改动

#### 3.2.1 `_handle_server_relay` 增强

```python
async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    # ... 现有逻辑不变 ...

    # ═══ 规则 2: ✅ 完成 → 转发PM + 自动确认 + AutoRouter（R88 新增）═══
    if content.startswith("✅ 完成"):
        # ⑤a 转发给 PM（现有逻辑）
        if pm_agent_id:
            await _broadcast_to_channel(...)
        
        # ⑤b 自动确认给 bot（现有逻辑）
        await _broadcast_to_channel(
            f"_inbox:{agent_id}",
            {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统(中继)",
                "from_agent": "system",
                "content": "✅ 确认，已收到你的完成通知。本轮任务完成。",
                "ts": time.time(),
            },
        )

        # ═══ R88 AutoRouter ═══
        # 从 _PIPELINE_CONFIG 读取管线拓扑
        round_name = _resolve_round_from_msg(msg)  # 从消息推断所属轮次
        pipeline_config = _PIPELINE_CONFIG.get(round_name, {})
        topology = pipeline_config.get("topology", {})
        auto_chain = topology.get("auto_chain", False) or pipeline_config.get("auto_chain", False)
        
        if auto_chain:
            current_step_name = _resolve_current_step(msg, pipeline_config, agent_id)
            if current_step_name:
                next_step = _resolve_next_step(current_step_name, topology, pipeline_config)
                if next_step:
                    # 有下一棒 → 自动派活
                    await _auto_dispatch_next(
                        round_name=round_name,
                        current_step=current_step_name,
                        next_step=next_step,
                        pipeline_config=pipeline_config,
                        prev_sha=sha,  # 从 content 提取
                    )
                else:
                    # 无下一棒 → 发送「全部完成」通知给 PM
                    await _broadcast_to_channel(
                        f"_inbox:{pm_agent_id}",
                        {
                            "type": "broadcast",
                            "channel": f"_inbox:{pm_agent_id}",
                            "from_name": "系统(中继)",
                            "from_agent": "system",
                            "content": f"🏁 {round_name} 全部 Step 已完成！管线自动闭环。",
                            "ts": time.time(),
                        },
                    )
        
        logger.info("[Relay] 完成: %s → PM + 自动确认 + AutoRouter(%s)", 
                     sender_name, "自动接力" if auto_chain else "跳过")
        return True
```

#### 3.2.2 新增函数：`_resolve_current_step`

```python
def _resolve_current_step(msg: dict, pipeline_config: dict, agent_id: str) -> str | None:
    """从完成消息推断当前是哪个 Step。
    
    策略（按优先级）：
    1. 消息内容中包含 "Step N" / "stepN" 引用 → 直接提取
    2. agent_id 匹配 pipeline_config 中某 step 的角色 → 返回该 step
    3. 从 _PIPELINE_STATE 读取当前活跃 step
    """
    content = msg.get("content", "")
    
    # 策略 1: 消息中有显式 Step 标记
    import re
    step_match = re.search(r'[Ss]tep\s*(\d+)', content)
    if step_match:
        return f"step{step_match.group(1)}"
    
    # 策略 2: 检查 agent_id 对应哪个 step
    steps = pipeline_config.get("steps", {})
    users = _r72_users  # 全局 agent 注册表
    agent_name = users.get(agent_id, {}).get("name", "")
    for step_key, step_cfg in steps.items():
        step_role = step_cfg.get("role", "")
        # 检查该 step 的 role 是否匹配当前 agent
        # （需要在 _cmd_pipeline_start 时记录 step→agent_id 映射）
        ...
    
    # 策略 3: 从管线状态读取
    from . import pipeline_state
    # pipeline_state 中有当前活跃的 step 记录
    ...
    
    return None
```

#### 3.2.3 新增函数：`_resolve_next_step`

```python
def _resolve_next_step(current_step: str, topology: dict, pipeline_config: dict) -> dict | None:
    """从管线拓扑中查询下一棒 Step。"""
    steps_topology = topology.get("steps", {})
    current_topology = steps_topology.get(current_step, {})
    next_step_name = current_topology.get("next")
    
    if not next_step_name:
        return None  # 终点
    
    steps = pipeline_config.get("steps", {})
    next_step_config = steps.get(next_step_name, {})
    if not next_step_config:
        return None  # 配置异常
    
    return {
        "step_name": next_step_name,
        "role": next_step_config.get("role", ""),
        "title": next_step_config.get("title", ""),
        "context": next_step_config.get("context", {}),
        "task_template": current_topology.get("task_template", _DEFAULT_TASK_TEMPLATE),
    }
```

#### 3.2.4 新增函数：`_auto_dispatch_next`

```python
async def _auto_dispatch_next(
    round_name: str,
    current_step: str,
    next_step: dict,
    pipeline_config: dict,
    prev_sha: str,
):
    """自动派发下一 Step 任务到目标 bot 的 inbox。"""
    next_role = next_step["role"]
    next_step_name = next_step["step_name"]
    
    # 1. 找下一棒 bot 的 agent_id
    #   从 _cmd_pipeline_start 时记录的 step→agent_id 映射中查找
    target_agent_id = _get_agent_id_for_role(round_name, next_role)
    if not target_agent_id:
        logger.warning("[AutoRouter] 未找到角色 %s 的 agent（round=%s）", next_role, round_name)
        return
    
    # 2. 生成任务消息
    #    使用 task_template 或默认模板
    template = next_step.get("task_template", _DEFAULT_TASK_TEMPLATE)
    task_content = _render_task_template(template, {
        "next_round": round_name,
        "next_step": next_step_name,
        "next_name": next_step.get("title", next_step_name),
        "next_title": next_step.get("title", next_step_name),
        "next_role": next_role,
        "next_context": _format_context(next_step.get("context", {})),
        "prev_role": _get_step_role(current_step, pipeline_config),
        "prev_sha": prev_sha,
        "prev_artifact_url": _infer_artifact_url(current_step, round_name),
    })
    
    # 3. 发送到目标 bot 的 inbox
    await _send_inbox_task(
        target_agent_id=target_agent_id,
        content=task_content,
        from_name="系统(管线)",
        context={
            "round_name": round_name,
            "pipeline_step": next_step_name,
            "previous_sha": prev_sha,
        },
    )
    
    logger.info(
        "[AutoRouter] %s %s 完成 → 自动派活 %s (%s → %s)",
        round_name, current_step, next_step_name, 
        _get_agent_name(agent_id),  # 当前 bot 名称
        _get_agent_name(target_agent_id),  # 下一棒 bot 名称
    )
```

#### 3.2.5 默认任务模板

```python
_DEFAULT_TASK_TEMPLATE = """【{next_round} Step {next_step} 任务 — {next_title} 🎯】

角色: {next_role}
前一棒已完成 ✅ `{prev_sha}`

参考：
{next_context}

请按流程完成任务后推 dev 分支。
✅ 完成，已推 dev: <sha>

完成后请回复 _inbox:server 告知 SHA。
"""
```

#### 3.2.6 `_cmd_pipeline_start` 增强

`!pipeline_start` 解析 frontmatter 后，读取 `topology` 字段（如存在），存入 `_PIPELINE_CONFIG[round_name]["topology"]`：

```python
if frontmatter:
    config_data = _build_pipeline_config(frontmatter, round_name, base_urls)
    # R88: 读取 topology 定义
    topology = frontmatter.get("pipeline", {}).get("topology", {})
    if topology:
        config_data["topology"] = topology
        logger.info("[R88] 管线 %s 启用了拓扑自动接力", round_name)
    # ... 写入 _PIPELINE_CONFIG ...
```

#### 3.2.7 `!_inbox:server` 命令检查（可选增强）

新增一条 `!` 子命令让 bot 查询当前管线的拓扑：

| 命令 | 响应 | 用途 |
|:-----|:-----|:------|
| `!pipeline_topology {round_name}` | 返回当前管线的 Step 链和下一棒 | Bot 可知道自己是管线中的哪一环 |

### 3.3 关键设计决策

#### 问题 1：AutoRouter 如何知道当前是哪个 Step？

**方案：多策略解析**

| 优先级 | 策略 | 场景 |
|:------:|:-----|:------|
| ① | ✅ 完成消息中显式包含 `Step N` 标记 | bot 回复中包含 `✅ 完成，已推 dev: abc1234 (Step 2)` |
| ② | agent_id → role → step 反向映射 | bot 的 agent_id 注册了 role=architect → 对应 step2 |
| ③ | 管线状态机当前活跃 Step | `pipeline_state` 记录的 `current_step` |

**推荐：** 实现策略 ②（agent_id 映射）作为主力，策略 ① 作为容错，策略 ③ 作为后备。

#### 问题 2：多 bot 同时完成，AutoRouter 是否会串？

不会。每个 `✅ 完成` 消息独立触发 AutoRouter：

- `_handle_server_relay` 是 per-message 处理器
- 两条 `✅ 完成` 消息先后到达，各自解析各自的 step→role→next
- 管线拓扑定义了每个 Step 的唯一下一棒，不会出现「一条完成触发两个下一棒」

**注意：** 如果某 Step 有多个并行完成者（未来场景），AutoRouter 只在第一个 `✅ 完成` 触发，后续的 `✅ 完成` 收到后检查状态机已前进（Step 已消费），不做重复派活。这在 R88 中不做，留 R89。

#### 问题 3：PM 安全守卫——PM 是否仍能手动介入？

**能。** AutoRouter 不会阻止 PM 手动派活或覆盖自动派活：

- PM 始终可以直接发 `_inbox:<bot_id>` 覆盖自动派活
- 自动派活发送时，如果该 bot 的 inbox 已有未完成的上次任务，不会自动取消——bot 的 LLM 自行判断优先级
- PM 可通过 `!pipeline_mode manual` 关闭 AutoRouter，回到纯手动模式

### 3.4 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **新增** — `_resolve_current_step()`, `_resolve_next_step()`, `_auto_dispatch_next()`, `_render_task_template()` | ~120 行 |
| `server/handler.py` | **修改** — `_handle_server_relay()` 规则 2 中增加 AutoRouter 调用 | ~30 行 |
| `server/handler.py` | **修改** — `_cmd_pipeline_start()` 读取 topology 字段 | ~10 行 |
| `server/config.py` | **新增** — `DEFAULT_TASK_TEMPLATE` 常量 + 可选 `auto_chain_default` | ~10 行 |
| **合计** | | **~170 行净增** |

### 3.5 不纳入范围

| 事项 | 原因 |
|:-----|:------|
| **并行 Step 拓扑** — 多个 Step 可同时执行（如方案评审与编码准备并行） | 6-Step 线性拓扑已覆盖 95% 场景，并行拓扑留 R89 |
| **异常回退** — bot 完成消息不合格式时自动回退到 PM 手动 | 初版直接报错到 PM，不影响现有逻辑 |
| **Step 跳过/跳步** — topology 支持 `skip: step5` | 非核心场景，未来扩展 |
| **动态拓扑修改** — 管线运行时修改 Step 链 | 拓扑在 pipeline_start 时固定，运行中不改 |
| **`!step_complete` 自动推进状态机** | R88 只做 inbox 派活，`!step_complete` 推进状态机是独立功能，沿用现有 `_cmd_step_complete` |
| **结构化 Task Card** — bot 间用 JSON/YAML 交接工作 | 初版用自然语言模板即可，结构化交接留 Phase 2 长期规划 |

---

## 4. 验收标准

### 🎯 4.1 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | frontmatter 定义 `topology` 被正确解析存入 `_PIPELINE_CONFIG` | `!pipeline_start` 后，`_PIPELINE_CONFIG[round_name]` 含 `topology` 字段 | 日志 grep "启用了拓扑自动接力" |
| ✅-2 | Step 2 bot 发 `✅ 完成` → server 自动派活 Step 3 | Step 3 bot 的 inbox 收到自动生成的任务消息 | 检查 Step 3 bot 收件箱 |
| ✅-3 | Step 3 bot 发 `✅ 完成` → server 自动派活 Step 4 | Step 4 bot 的 inbox 收到任务 | 同上 |
| ✅-4 | Step 4 → Step 5, Step 5 → Step 6 | 全线自动接力，PM 未手动发任何一条中间派活 | 日志统计 AutoRouter 触发次数 |
| ✅-5 | Step 6 bot 发 `✅ 完成` → server 发「全部完成通知」给 PM | PM 收到 `🏁 R{轮次} 全部 Step 已完成！管线自动闭环。` | 检查 PM 收件箱 |
| ✅-6 | 自动派活消息包含正确的 SHA 引用 | Step 3 任务中引用了 Step 2 的 commit SHA | 检查任务内容 |
| ✅-7 | 自动派活消息包含正确的 context URL | Step 3 任务中提及 tech_plan_url | 同上 |
| ✅-8 | 无 topology 定义的管线不受影响 | PM 手动接力模式仍正常工作 | 旧格式管线发 `✅ 完成` → 不触发 AutoRouter |
| ✅-9 | `auto_chain: false` 时不触发 AutoRouter | 即使有 topology 但 disable 了，不自动接力 | 设置 false → 发完成 → 无自动派活 |

### 🎯 4.2 安全与兼容

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-10 | PM 手动派活时 AutoRouter 不会冲突 | 自动派活和手动派活都可到达 bot inbox，bot 按 LLM 逻辑处理 |
| ✅-11 | `!pipeline_mode manual` 期间不触发 AutoRouter | 手动模式下 AutoRouter 静默跳过 |
| ✅-12 | bot 发非标格式（`✅ 完成` 前有多余字符）→ 不触发 AutoRouter | 仅 `✅ 完成` 前缀精确匹配才触发 |
| ✅-13 | AutoRouter 派活失败（找不到角色 agent）→ 日志报错 + 通知 PM | PM 收到 ❌ 通知，AotuRouter 不阻塞现有 `✅ 完成` 处理 |
| ✅-14 | Step 6 完成后 AutoRouter 不再派活 | step6 的 next=null 或不存在 → 正确发「全部完成」通知 |

### 🎯 4.3 文档更新

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-15 | `inbox-message-protocol.md` 更新 | §8 全流程更新为 AutoRouter 自动接力模型 |
| ✅-16 | TODO.md Phase 2 更新 | AutoRouter 标记完成，更新版本号 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:----:|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 5min |
| **2** | 👷 Arch | 技术方案（含拓扑解析、AutoRouter 伪代码、角色映射策略） | 10min |
| **3** | 👨‍💻 Dev | 编码实现（~170 行净增） | 20min |
| **4** | 👀 Review | 代码审查（重点：拓扑解析鲁棒性、角色映射准确性） | 10min |
| **5** | 🦐 QA | 测试报告（14 项验收 + 3 端到端场景） | 15min |
| **6** | 🛠️ Operations | 合并部署 + 更新 TODO.md + inbox-message-protocol.md §8 | 10min |

### 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| **Step 推断错误** — AutoRouter 无法准确判断当前完成的 Step | 派错下一棒，任务发给错误的 bot | 多策略回退（消息显式标记 → agent_id 映射 → 状态机）；所有推断失败时通知 PM 手动处理 |
| **bot 的 `✅ 完成` 消息不包含 Step 标记** | 策略 ① 失败，需依赖策略 ②/③ | R86 以来的协议已建议 bot 在完成消息中包含轮次标记，R88 进一步建议包含 Step 标记 |
| **agent_id 映射在 server 重启后丢失** | 策略 ② 找不到 bot | agent 注册表 `_r72_users` 通过持久化存储恢复，R72 已解决 |
| **拓扑定义错误** — frontmatter 中 steps/role 写错 | AutoRouter 找不到目标 agent | 启动时校验拓扑完整性，发现未定义的 step/role 则报错 |
| **bot 离线** — 自动派活时目标 bot 不在线 | 任务发了但 bot 没收到 | 现有 inbox 持久化机制保证消息投递（bot 上线后收），无需额外处理 |
| **并行完成消息** — 上下步同时完成 | 消息短时间窗口内平行触发 | per-message 独立处理策略保证不会串线 |

---

## 6. R88 与 Roadmap 的对应关系

```
Phase 1 — 稳定 Inbox ✅
       ↓
Phase 2 — 自动化管线（进行中）
       ├── ✅ R87: `_inbox:server` 中继架构
       ├── 🔄 **R88: Pipeline AutoRouter** ← 当前轮次
       ├── 🔲 R89: 异常回退 + 并行拓扑
       ├── 🔲 R90: 结构化 Task Card
       └── 🔲 R91: 管线监控增强
       ↓
Phase 3 — Coder Agent 编码专精（待启动）
```

---

## 7. 完整端到端场景

### 场景：标准 6-Step 管线自动运行

```
1. PM 发 !pipeline_start R88 ...  (frontmatter 含 topology)
   ├─ Server 解析 frontmatter → _PIPELINE_CONFIG[R88].topology
   └─ Server 创建工作室 → 通知全员

2. PM 派活 Step 2 给 arch → _inbox:arch
   （PM 只需发这 1 条派活消息，后续全自动）

3. arch 收活 → ACK ✅ → 出技术方案 → 推 dev → ✅ 完成
   ├─ Server 转发进度给 PM（现有 R87 逻辑）
   ├─ Server 自动确认给 arch（现有 R87 逻辑）
   └─ 🆕 AutoRouter → 派活 Step 3 给 dev

4. dev 收活 → ACK ✅ → 编码 → 推 dev → ✅ 完成
   ├─ Server 转发 + 确认（现有）
   └─ 🆕 AutoRouter → 派活 Step 4 给 reviewer

5. reviewer → ✅ 完成
   └─ 🆕 AutoRouter → 派活 Step 5 给 qa

6. qa → ✅ 完成
   └─ 🆕 AutoRouter → 派活 Step 6 给 operations

7. operations → ✅ 完成
   └─ 🆕 AutoRouter → 发「全部完成」通知给 PM

PM 查看收件箱：7 条消息（1 条派活 + 6 条进度通知 + 1 条全部完成通知）
对比 R87：PM 需发 6 条派活 + 手动维护 Step 顺序
```

**R88 后 PM 操作量对比：**

| 轮次 | PM 派活次数 | 手动接力次数 | 全程需关注度 |
|:----:|:----------:|:------------:|:-----------:|
| R76（纯手动） | 6 | 5 | 🔴 高 — 全程手动 |
| R87（中继） | 6 | 5 | 🟡 中 — 转发自动了，但仍需手动发下一棒 |
| **R88（AutoRouter）** | **1** | **0** | 🟢 **低 — 派活1条，通知收尾即可** |

---

## 8. 脱敏检查清单

- [ ] docs/R88/*.md 零内部名残留（frontmatter 的角色 mapping 除外）
- [ ] 使用通用角色名（PM / arch / dev / review / qa / operations）
- [ ] 不包含真实 agent_id / token / URL
- [ ] 拓扑示例中的 bot 名称用 placeholder（如 bot_A, bot_B 或 agent_arch, agent_dev）
