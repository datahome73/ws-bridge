# R88 产品需求 — 管线自动路由：Pipeline AutoRouter 🚂

> **版本：** v2.0（PM 审核修訂 — Step 1 是 PM 的工作，非手动派活）
> **状态：** 📝 待审核
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
│  PM 仍需手动发送下一棒的派活     ←──────── 无自动接力 ──────────────│
```

**核心问题：** PM 每完成一个 Step 都要手动给下个 bot 发派活消息。每个轮次 PM 手动派活 5+ 次。

### 1.2 正确的思路

**PM 本身就是管线的一环——Step 1。**

| 轮次 | Step | 角色 | 工作内容 |
|:----:|:----:|:-----|:---------|
| 🅰️ | **Step 1** | **📋 PM** | 写需求文档 + WORK_PLAN（含 frontmatter 拓扑定义）+ `!pipeline_start` |
| 🅱️ | Step 2 | 👷 Arch | 技术方案设计 |
| 🅲 | Step 3 | 👨‍💻 Dev | 编码实现 |
| 🅳 | Step 4 | 👀 Review | 代码审查 |
| 🅴 | Step 5 | 🦐 QA | 测试验证 |
| 🅵 | Step 6 | 🛠️ Ops | 合并部署归档 |

**PM 完成 Step 1 后，server 收到完成信号，按同一套 AutoRouter 规则自动转 Step 2 给 arch（架构师）。** arch 收到的任务消息和 PM 手动派活时一模一样——bot 不 care 消息是谁发的。

> 📌 **对 bot 来说：通信方式完全没变化。** 任务消息的 channel 是 `_inbox:<bot_id>`，bot 该 ACK 就 ACK，该干活就干活。只是消息的 `from_name` 从「PM」变成「系统(管线)」，bot 不需要做任何适配改动。

---

## 2. 方案设计

### 2.1 核心概念

**Pipeline Topology（管线拓扑）** 定义：
- 完整的 Step 链（Step 1 PM → Step 2 arch → ... → Step 6 ops）
- 每个 Step 的产出上下文（文档 URL、变量）
- Step 间自动接力规则（完成→自动派活下一棒）
- **Step 1 由 PM 完成，Step 1 到 Step 2 的自动接力由 `!pipeline_start` 触发**

### 2.2 通信流（R88 后）

对 bot 而言，和现在一模一样的收消息 → ACK → 干活 → ✅ 完成，唯一区别是消息来自 server 不是 PM：

```
PM                                Server                              Bot A
│                                  │                                  │
│① Step 1: 写需求+WORK_PLAN       │                                  │
│   → !pipeline_start R88 ...     │                                  │
│                                  │                                  │
│② 收到: Step 1 完成, 准备派活    │                                  │
│←── 确认: Step 1 配置就绪 ──────┤                                  │
│                                  │                                  │
│                                  │── ③ AutoRouter Step 1→2 ─────→│
│                                  │    _inbox:arch                  │
│                                  │    "Step 2 任务：技术方案"       │
│                                  │                                  │
│         [bot 体验完全不变]       │←── ④ ACK ✅ R88 收到！────────┤
│                                  │         (_inbox:server)          │
│←── ⑤ 转发 ACK ──────────────────┤                                  │
│                                  │                                  │
│                                  │         [arch 干活中...]        │
│                                  │                                  │
│                                  │←── ⑥ ✅ 完成 ──────────────────┤
│                                  │     (_inbox:server)              │
│←── ⑦ 转发 完成 ────────────────┤                                  │
│                                  │── ⑧ 自动确认 bot ────────────→│
│                                  │── ⑨ AutoRouter Step 2→3 ─────→│
│                                  │    _inbox:dev                   │
│                                  │    "Step 3 任务：编码实现"       │
│                                  │                                  │
│                           ... 以此类推到 Step 6 ...                │
│                                  │                                  │
│                                  │←── ⑩ Step 6 ops ✅ 完成 ─────┤
│                                  │── ⑪ 「全部完成」通知 PM ──────→│
│←── 🏁 全线闭环 ───────────────────┤                                  │
```

**PM 视角：** Step 1 工作准备 → `!pipeline_start` → 坐等通知 → 收全部完成。

**Bot 视角：** 收到 `_inbox:<bot_id>` 任务（from_name=`系统(管线)` 而不是 PM 名字）→ ACK → 干活 → ✅ 完成。和现在一样的通信协议，啥也不用改。

### 2.3 Key Insight：bot 不 care 谁发的消息

| 维度 | R87（PM 手派） | R88（Server 自动派） | Bot 感知差异 |
|:-----|:--------------|:--------------------|:------------|
| 消息 channel | `_inbox:<bot_id>` | `_inbox:<bot_id>` | **无变化** |
| 消息内容 | 任务描述 | 任务描述（自动生成） | **无变化** |
| `from_name` | `PM` | `系统(管线)` | 仅名字不同 |
| 回复地址 | `_inbox:server` | `_inbox:server` | **无变化** |
| 协议（ACK/完成） | `ACK ✅` / `✅ 完成` | `ACK ✅` / `✅ 完成` | **无变化** |

**== 对 bot 来说是完全透明的 ==** bot 不需要任何改动。

### 2.4 PM 在管线中的位置

PM 是**管线的一环**，不是「站在管线外的人」。

```
Step 1 ──→ Step 2 ──→ Step 3 ──→ Step 4 ──→ Step 5 ──→ Step 6
 👤PM       👷Arch     👨‍💻Dev     👀Review   🦐QA      🛠️Ops
```

PM 的 Step 1 工作包括：
1. 写需求文档 `docs/R{N}/R{N}-product-requirements.md`
2. 写 WORK_PLAN `docs/R{N}/WORK_PLAN.md`（含 frontmatter 拓扑定义）
3. 执行 `!pipeline_start R{N} --work_plan_url <raw_url>` — **此命令即 Step 1 完成信号**

**Step 1 的产出：**
- `_PIPELINE_CONFIG[round_name]` — 完整的管线配置（steps, topology, context）
- 已创建的工作区（workspace）
- 可用于后续 Step 的基础上下文（work_plan_url, requirements_url, topology 定义）

### 2.5 关键设计原则

| # | 原则 | 说明 |
|:-:|:-----|:------|
| 1 | **不引入新持久化状态** | Pipeline Topology 直接从 `_PIPELINE_CONFIG` 读取，不新增状态表 |
| 2 | **不改变 bot 协议** | Bot 的 ACK/完成协议完全不变，bot 零改动 |
| 3 | **向后兼容** | 无 Pipeline Topology 定义的管线照常运行（PM 手动接力）— 拓扑是可选项 |
| 4 | **PM 是 Step 1** | PM 不是「派活的人」，是管线自动化的一部分 |
| 5 | **`!pipeline_start` = Step 1 完成** | 此命令触发 Step 1→Step 2 自动接力 |
| 6 | **Bot 透明** | Bot 不 care 任务是谁发的——消息结构完全一样 |

---

## 3. 实现方案

### 3.1 Pipeline Topology 定义

#### 3.1.1 WORK_PLAN frontmatter 扩展

在 `pipeline` 字段中增加 `topology` 定义：

```yaml
pipeline:
  name: "R88 Pipeline AutoRouter"
  work_plan_url: "https://raw.githubusercontent.com/.../docs/R88/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/.../docs/R88/R88-product-requirements.md"

  topology:                              # ← 🆕 管线拓扑定义
    auto_chain: true                     # 启用自动接力
    chain:                               # Step 链（有序列表）
      - step: step2
        role: architect
        title: 技术方案
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step3
        role: developer
        title: 编码实现
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          requirements_url: "${pipeline.requirements_url}"
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署归档
        context:
          requirements_url: "${pipeline.requirements_url}"
          test_report_url: "docs/{round}/{round}-test-report.md"

  steps:                                 # 兼容现有格式（用于 !step_complete 等）
    step2:
      role: architect
      title: 技术方案
    step3:
      role: developer
      title: 编码实现
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署归档
```

**关于 `chain` vs 现有的 `steps`：**
- `topology.chain` — **新字段**，顶级管线拓扑定义，基于数组的有序 Step 链，表达 Step 1→2→3... 的自动接力关系
- `steps` — **现有字段**，用于 `!step_complete` 等命令的 Step 配置（backward compat）
- 两者并存但不冲突：`chain` 面向 AutoRouter，`steps` 面向状态机

**`topology.chain` 的结构优势：**
- **有序数组** — 天然表达 Step 执行顺序，第 N 个元素完成后 → 第 N+1 个元素自动派活
- **自包含** — 每个 Step 定义了自己的 role、title、context，不需要去 `steps` 反向查找
- **可扩展** — 未来可支持 `parallel: true` 实现并行 Step

#### 3.1.2 简写格式

对于标准 6-Step 管线，支持省略 `topology.chain`，使用默认 Step 排序：

```yaml
pipeline:
  auto_chain: true                       # ← 仅需 1 行
  steps:
    step2: { role: architect, ... }
    step3: { role: developer, ... }
    step4: { role: reviewer, ... }
    step5: { role: qa, ... }
    step6: { role: operations, ... }
```

默认规则：按 step_key 的数字排序（step2→step3→step4→step5→step6），step6 为终点。

#### 3.1.3 Task 模板变量

自动生成的任务消息中可使用的变量：

| 变量 | 来源 | 说明 |
|:-----|:------|:------|
| `{round}` | pipeline.name / round_name | 当前轮次名（如 R88） |
| `{step}` | chain 中的 step key | 当前 Step（如 step3） |
| `{role}` | chain 中的 role | 当前角色的通用名（如 developer） |
| `{title}` | chain 中的 title | 当前 Step 的标题（如 编码实现） |
| `{prev_sha}` | 从 `✅ 完成` 消息提取 | 前一棒的产出 SHA |
| `{prev_role}` | chain 中前一个元素的 role | 前一棒角色名 |
| `{prev_title}` | chain 中前一个元素的 title | 前一棒的标题 |
| `{context}` | chain 中的 context 字典拼接 | 注入的文档 URL 引用列表 |

#### 3.1.4 默认任务模板

```python
_DEFAULT_TASK_TEMPLATE = """【{round} Step {step} 任务 — {title} 🎯】

角色: {role}
前一棒 {prev_role} 已完成 ✅ `{prev_sha}`

参考：
{context}

请按流程完成任务后推 dev 分支。
完成后请回复 _inbox:server 告知 SHA。
"""
```

### 3.2 Server 端改动

#### 3.2.1 `!pipeline_start` → Step 1 完成 → AutoRouter 触发

核心逻辑：`!pipeline_start` 完成后，不再等待 PM 手动派活 Step 2，而是**直接触发 AutoRouter 从 Step 1 转到 Step 2**。

```python
async def _cmd_pipeline_start(ws, agent_id, msg, ...):
    # ... 现有解析 frontmatter、创建 workspace、配置管线等逻辑不变 ...

    # ── 读取 topology 定义 ──
    topology = frontmatter.get("pipeline", {}).get("topology", {})
    if topology:
        config_data["topology"] = topology
        logger.info("[R88] 管线 %s 启用了拓扑自动接力", round_name)
    
    # ... 写入 _PIPELINE_CONFIG ...
    
    # ═══ R88: Step 1 完成 → AutoRouter 触发 Step 1→Step 2 ═══
    # PM 已经完成了 Step 1（写文档+启动管线），这里是 Step 1 的完成信号
    # AutoRouter 读取拓扑链，从第 1 个 Step（step2）开始派活
    auto_chain = topology.get("auto_chain", False) or config_data.get("auto_chain", False)
    if auto_chain:
        chain = topology.get("chain", [])
        if chain:
            first_step = chain[0]  # step2
            # 派活 Step 2 给 arch
            await _auto_dispatch_step(
                round_name=round_name,
                step_config=first_step,
                chain=chain,
                pipeline_config=config_data,
                prev_sha="",         # Step 1 是需求文档 + WORK_PLAN SHA
                prev_role="PM",
                prev_title="需求与计划",
            )
            logger.info("[R88] %s Step 1 完成 → 自动派活 Step 2 (%s)", 
                       round_name, first_step.get("role", "?"))
        else:
            # 简写格式：按 steps 的 step_key 排序
            steps_sorted = _get_sorted_steps(config_data.get("steps", {}))
            if steps_sorted:
                first_step_name = steps_sorted[0]
                first_step_cfg = config_data["steps"][first_step_name]
                await _auto_dispatch_step(
                    round_name=round_name,
                    step_name=first_step_name,
                    step_config=first_step_cfg,
                    chain=None,
                    pipeline_config=config_data,
                    prev_sha="",
                    prev_role="PM",
                    prev_title="需求与计划",
                )
```

#### 3.2.2 `_handle_server_relay` 增强 — 规则 2 AutoRouter

当 bot 发 `✅ 完成` 时，server 不仅转发和自动确认（R87 逻辑），还触发 AutoRouter 找下一棒：

```python
# 在 _handle_server_relay 规则 2（✅ 完成）中增加 AutoRouter

if content.startswith("✅ 完成"):
    # ⑤a 转发给 PM（现有 R87 逻辑 — 不变）
    if pm_agent_id:
        await _broadcast_to_channel(...)
    
    # ⑤b 自动确认给 bot（现有 R87 逻辑 — 不变）
    await _broadcast_to_channel(
        f"_inbox:{agent_id}", {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统(中继)",
            "from_agent": "system",
            "content": "✅ 确认，已收到你的完成通知。",
            "ts": time.time(),
        },
    )
    
    # ═══ R88 AutoRouter: ✅ 完成 → 自动派活下一棒 ═══
    await _auto_router_on_completion(
        round_name=round_name,  # 从 context 推断
        agent_id=agent_id,      # 完成的 bot
        content=content,        # 完成消息（含 SHA）
    )
    
    return True
```

#### 3.2.3 新增函数：`_auto_router_on_completion`

```python
async def _auto_router_on_completion(
    round_name: str,
    agent_id: str,
    content: str,
) -> None:
    """Bot 完成 Step 后，AutoRouter 查找下一棒并自动派活。
    
    不阻塞调用方——派活失败不会影响 ⑤a/⑤b 的执行。
    """
    pipeline_config = _PIPELINE_CONFIG.get(round_name, {})
    if not pipeline_config:
        logger.debug("[AutoRouter] %s 无管线配置，跳过", round_name)
        return
    
    auto_chain = pipeline_config.get("topology", {}).get("auto_chain", False) \
                 or pipeline_config.get("auto_chain", False)
    if not auto_chain:
        return  # 未启用自动接力
    
    chain = pipeline_config.get("topology", {}).get("chain", [])
    if not chain:
        # 简写模式：按 steps key 排序
        sorted_steps = _get_sorted_steps(pipeline_config.get("steps", {}))
        if not sorted_steps:
            return
        # 找当前 agent_id 对应的 step 在链中的位置
        current_idx = _find_step_index_by_agent(agent_id, sorted_steps, pipeline_config)
    else:
        # 标准模式：找 chain 中当前 agent_id 对应的元素位置
        current_idx = _find_step_index_in_chain(agent_id, chain, pipeline_config)
    
    if current_idx is None:
        logger.debug("[AutoRouter] %s 未找到当前 Step（agent=%s）", round_name, agent_id[:12])
        return
    
    next_idx = current_idx + 1
    
    if chain:
        # 标准模式：读取 chain[next_idx]
        if next_idx >= len(chain):
            # 终点 — 全部完成
            await _notify_pipeline_complete(round_name)
            return
        next_step = chain[next_idx]
        prev_step = chain[current_idx] if current_idx < len(chain) else {}
    else:
        # 简写模式
        if next_idx >= len(sorted_steps):
            await _notify_pipeline_complete(round_name)
            return
        next_step_name = sorted_steps[next_idx]
        next_step = pipeline_config["steps"].get(next_step_name, {})
        prev_step_name = sorted_steps[current_idx]
        prev_step = pipeline_config["steps"].get(prev_step_name, {})
    
    # 提取 SHA
    sha = _extract_sha(content)
    
    # 派活下一棒
    await _auto_dispatch_step(
        round_name=round_name,
        step_config=next_step,
        chain=chain or None,
        pipeline_config=pipeline_config,
        prev_sha=sha or "",
        prev_role=prev_step.get("role", "?"),
        prev_title=prev_step.get("title", "?"),
        step_name=next_step_name if not chain else None,
    )
```

#### 3.2.4 新增函数：`_auto_dispatch_step`

```python
async def _auto_dispatch_step(
    round_name: str,
    step_config: dict,
    chain: list | None,
    pipeline_config: dict,
    prev_sha: str,
    prev_role: str,
    prev_title: str,
    step_name: str | None = None,
) -> None:
    """派活指定 Step 到目标 bot 的 inbox。
    
    Args:
        step_config: chain 中的元素或 steps 中的配置
        chain: 完整 chain（为 None 时使用简写模式用 step_name 定位）
    """
    if chain:
        role = step_config.get("role", "")
        title = step_config.get("title", "")
        step_key = step_config.get("step", step_name or "")
    else:
        role = step_config.get("role", "")
        title = step_config.get("title", "")
        step_key = step_name or ""
    
    if not role:
        logger.warning("[AutoRouter] Step %s 缺少 role 定义，跳过自动派活", step_key)
        return
    
    # 找目标 bot 的 agent_id
    target_agent_id = _get_agent_id_for_role(round_name, role)
    if not target_agent_id:
        logger.warning("[AutoRouter] 角色 %s 无对应 agent（round=%s），通知 PM", role, round_name)
        pm_agent_id = config.PIPELINE_PM_AGENT_ID
        if pm_agent_id:
            await _broadcast_to_channel(
                f"_inbox:{pm_agent_id}", {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统(管线)",
                    "from_agent": "system",
                    "content": f"❌ AutoRouter 无法派活 {step_key}（角色={role}）：未找到对应 bot。\n"
                              f"请手动派活到正确的 bot 收件箱。",
                    "ts": time.time(),
                },
            )
        return
    
    # 构建任务消息
    context_lines = []
    for k, v in step_config.get("context", {}).items():
        if v:
            context_lines.append(f"- {k}: {v}")
    context_str = "\n".join(context_lines) if context_lines else "（参考上下文见 WORK_PLAN）"
    
    # 使用默认模板
    task_content = (
        f"【{round_name} Step {step_key} 任务 — {title} 🎯】\n\n"
        f"角色: {role}\n"
        f"前一棒 {prev_role} 已完成 ✅ `{prev_sha}`\n\n"
        f"参考：\n{context_str}\n\n"
        f"请按流程完成任务后推 dev 分支。\n"
        f"完成后请回复 _inbox:server 告知 SHA。"
    )
    
    # 发送到目标 bot inbox
    await _send_inbox_task(
        target_agent_id=target_agent_id,
        content=task_content,
        from_name="系统(管线)",
        context={
            "round_name": round_name,
            "pipeline_step": step_key,
            "previous_sha": prev_sha,
        },
    )
    
    logger.info(
        "[AutoRouter] %s 自动派活 %s (%s → %s)",
        round_name, step_key, prev_role, role,
    )
```

#### 3.2.5 辅助函数

```python
def _find_step_index_in_chain(agent_id: str, chain: list, pipeline_config: dict) -> int | None:
    """在 chain 中找当前 agent_id 对应的 position。"""
    role = _get_role_for_agent(agent_id, pipeline_config)
    if not role:
        return None
    for i, step in enumerate(chain):
        if step.get("role") == role:
            return i
    return None


def _find_step_index_by_agent(agent_id: str, sorted_steps: list, pipeline_config: dict) -> int | None:
    """在 sorted_steps 中找当前 agent_id 对应的 position。"""
    role = _get_role_for_agent(agent_id, pipeline_config)
    if not role:
        return None
    steps_cfg = pipeline_config.get("steps", {})
    for i, step_key in enumerate(sorted_steps):
        if steps_cfg.get(step_key, {}).get("role") == role:
            return i
    return None


def _get_role_for_agent(agent_id: str, pipeline_config: dict) -> str | None:
    """从管线配置中找 agent_id 映射的角色名。"""
    # 从 _r72_users 获取 agent 信息
    agent_info = _r72_users.get(agent_id, {})
    agent_name = agent_info.get("name", "")
    
    # 从 Agent Card 获取 pipeline_roles
    cards = ac_mod.get_all_cards()
    for card_id, card in cards.items():
        if card.get("agent_id") == agent_id:
            roles = card.get("pipeline_roles", {})
            return next(iter(roles.keys()), None)
    
    # Fallback: 从 workspace members 匹配
    workspace_members = pipeline_config.get("workspace", {}).get("members", {})
    for role_name, role_cfg in workspace_members.items():
        keywords = role_cfg.get("mention_keyword", "")
        if agent_name in keywords:
            return role_name
    
    return None


def _get_sorted_steps(steps: dict) -> list:
    """按 step key 的数字排序返回有序列表。"""
    import re
    def sort_key(k):
        m = re.match(r'step(\d+)', k.lower())
        return (int(m.group(1)),) if m else (0, k)
    return sorted(steps.keys(), key=sort_key)


def _extract_sha(content: str) -> str | None:
    """从 ✅ 完成消息中提取 commit SHA。"""
    import re
    # 匹配 "已推 dev: abc1234" 或 "commit abc1234" 或 "SHA: abc1234"
    m = re.search(r'(?:已推 dev[:\s]+|commit[:\s]+|SHA[:\s]*)([0-9a-f]{7,40})', content)
    if m:
        return m.group(1)
    return None


async def _notify_pipeline_complete(round_name: str) -> None:
    """管线全部 Step 完成 → 通知 PM。"""
    pm_agent_id = config.PIPELINE_PM_AGENT_ID
    if not pm_agent_id:
        return
    await _broadcast_to_channel(
        f"_inbox:{pm_agent_id}", {
            "type": "broadcast",
            "channel": f"_inbox:{pm_agent_id}",
            "from_name": "系统(管线)",
            "from_agent": "system",
            "content": f"🏁 {round_name} 全部 Step 已完成！管线自动闭环。",
            "ts": time.time(),
        },
    )
```

#### 3.2.6 `_cmd_pipeline_start` 修改点

在现有 `_cmd_pipeline_start` 中增加：

1. 解析 `topology` 字段 → 存入 `_PIPELINE_CONFIG[round_name]["topology"]`
2. 判断 `auto_chain` 是否开启
3. 若开启 → 读取 `chain[0]`（或 `steps` 排序后的第一个）→ 自动派活 Step 2

```python
# 在 _cmd_pipeline_start 末尾，workspace 创建成功后：

# R88: Step 1 完成 → AutoRouter
topology = config_data.get("topology", {})
auto_chain = topology.get("auto_chain", False) or config_data.get("auto_chain", False)

if auto_chain:
    chain = topology.get("chain", [])
    if chain:
        # 标准模式：chain[0] = step2
        first_step = chain[0]
        await _auto_dispatch_step(
            round_name=round_name,
            step_config=first_step,
            chain=chain,
            pipeline_config=config_data,
            prev_sha="",  # Step 1 产出是需求文档 + WORK_PLAN
            prev_role="PM",
            prev_title="需求与计划",
        )
    else:
        # 简写模式：按 steps 排序取第一个
        sorted_steps = _get_sorted_steps(config_data.get("steps", {}))
        if sorted_steps:
            first_key = sorted_steps[0]
            first_cfg = config_data["steps"][first_key]
            await _auto_dispatch_step(
                round_name=round_name,
                step_config=first_cfg,
                chain=None,
                pipeline_config=config_data,
                prev_sha="",
                prev_role="PM",
                prev_title="需求与计划",
                step_name=first_key,
            )
```

#### 3.2.7 Step 1 完成信号

`!pipeline_start` 就是 Step 1 的完成信号。PM 在启动管线前已完成 Step 1 工作：
- × 写需求文档 ✅
- × WORK_PLAN 含 frontmatter ✅
- × 已推 dev ✅
- → 执行 `!pipeline_start` = Step 1 完成

**不需新增 `!step1_complete`、`✅ 完成 Step 1` 等信号。**

### 3.3 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **新增** — `_auto_router_on_completion()`, `_auto_dispatch_step()`, `_find_step_index_in_chain()`, `_find_step_index_by_agent()`, `_get_role_for_agent()`, `_get_sorted_steps()`, `_extract_sha()`, `_notify_pipeline_complete()` | ~180 行 |
| `server/handler.py` | **修改** — `_handle_server_relay()` 规则 2 中增加 AutoRouter 调用 | ~10 行 |
| `server/handler.py` | **修改** — `_cmd_pipeline_start()` 解析 topology + AutoRouter 触发 | ~30 行 |
| **合计** | | **~220 行净增**（全 server 端，bot 端零改动） |

### 3.4 不纳入范围

| 事项 | 原因 |
|:-----|:------|
| **并行 Step 拓扑** — chain 支持 `parallel: true` | 线性 6-Step 先跑通，并行拓展开启 R89 |
| **异常回退** — bot 完成消息不合格式时自动回退 PM | v1 直接通知 PM 手动处理，不影响现有逻辑 |
| **Step 跳过** | 非核心场景，未来扩展 |
| **动态拓扑修改** — 管线运行时改 Step 链 | 拓扑在 `!pipeline_start` 时固定 |
| **结构化 Task Card** — bot 间用 JSON/YAML 交接 | 自然语言模板先跑通，结构化留后面 |
| **`!step_complete` 推进状态机** | 和 AutoRouter 是独立功能，各有各的推进方式 |

---

## 4. 验收标准

### 🎯 4.1 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `!pipeline_start` 含 topology → 解析成功存入 `_PIPELINE_CONFIG` | 日志打印 "启用了拓扑自动接力" | 启动管线 → grep 日志 |
| ✅-2 | `!pipeline_start` 后自动派活 Step 2（arch） | arch inbox 收到任务消息（from_name="系统(管线)"） | 检查 arch 收件箱 |
| ✅-3 | arch 发 `✅ 完成` → server 自动派活 Step 3（dev） | dev inbox 收到任务消息 | 检查 dev 收件箱 |
| ✅-4 | Step 3 → 4, Step 4 → 5, Step 5 → 6 全线自动 | 全部自动接力，PM 未手动发任何一条中间派活 | 日志统计 AutoRouter 触发次数 |
| ✅-5 | Step 6 ops 发 `✅ 完成` → server 发「全部完成」通知 PM | PM 收到 `🏁 R{轮次} 全部 Step 已完成！` | 检查 PM 收件箱 |
| ✅-6 | 自动派活消息包含正确的 `prev_sha` 引用 | Step 3 任务中引用了 Step 2 的 commit SHA | 检查任务内容 |
| ✅-7 | 自动派活消息包含正确的 context URL | 任务中提及前一棒的文档 URL | 检查任务内容 |
| ✅-8 | 无 topology 定义的管线不受影响 | PM 手动接力模式仍正常工作 | 旧格式管线发 `!pipeline_start` → 无自动派活 |
| ✅-9 | `auto_chain: false` 时不触发 AutoRouter | 即使写了 topology 但关闭了，不自动接力 | 设置 false → 启动 → 无自动派活 |

### 🎯 4.2 bot 透明性验证

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-10 | Bot 收到 server 派活后，按正常协议发 ACK ✅ | Bot 的 ACK 协议不变 |
| ✅-11 | Bot 正常干活、正常 `✅ 完成` | Bot 的工作流不变 |
| ✅-12 | Bot 从 `from_name` 字段知道消息来源 | `from_name="系统(管线)"` 显示在消息中 |
| ✅-13 | Bot 不因发送者不同而改变回复目标 | 回复地址仍是 `_inbox:server`（不变） |

### 🎯 4.3 安全与兼容

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-14 | PM 手动派活和 AutoRouter 并行不冲突 | 两条消息都可到达 bot inbox，bot LLM 自行判断 |
| ✅-15 | AutoRouter 找不到目标 agent → 通知 PM + 继续 | PM 收到 ❌ 通知，AotuRouter 不影响现有 `✅ 完成` 处理 |
| ✅-16 | `!pipeline_mode manual` 期间 AutoRouter 静默跳过 | 手动模式下不触发自动派活 |
| ✅-17 | `✅ 完成` 格式不匹配 → 不触发 AutoRouter | 仅 `✅ 完成` 精确前缀匹配 |
| ✅-18 | server 重启后 `_PIPELINE_CONFIG` 恢复 | Agent Card 持久化恢复角色映射（R72/R73 已解决） |

### 🎯 4.4 文档更新

| # | 检查项 |
|:-:|:-------|
| ✅-19 | `inbox-message-protocol.md` §8 更新为 AutoRouter 模型 |
| ✅-20 | TODO.md Phase 2 + 版本号更新 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:----:|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| 🅰️ **Step 1** | **📋 PM** | WORK_PLAN.md（含 topology 定义）→ `!pipeline_start` | 5min |
| 🅱️ **Step 2** | 👷 Arch | 技术方案（含 chain 解析、AutoRouter 伪代码、角色映射） | 10min |
| 🅲 **Step 3** | 👨‍💻 Dev | 编码实现（~220 行净增） | 20min |
| 🅳 **Step 4** | 👀 Review | 代码审查（重点：拓扑解析鲁棒性、角色映射准确性） | 10min |
| 🅴 **Step 5** | 🦐 QA | 测试报告（20 项验收 + 3 端到端场景） | 15min |
| 🅵 **Step 6** | 🛠️ Ops | 合并部署 + 更新 TODO.md + inbox-message-protocol.md §8 | 10min |

### 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| **角色映射不准** — `_get_role_for_agent` 找不到 agent | AutoRouter 无法派活 Step | 通知 PM 手动派活 + 日志报错，不阻塞现有转发逻辑 |
| **bot 未回 ACK** — 派活了但不回 ACK | PM 不知道 bot 是否收到 | 现有 R87 中继不依赖 ACK —— PM 从转发通知得知 |
| **`!pipeline_start` 后 workspace 创建失败** | Step 2 派活了但无 workspace | Step 2 的任务消息可以直接送到 inbox，不依赖 workspace |
| **chain 配置错误** — role 名与实际注册名不匹配 | AutoRouter 找不到 agent | 启动时校验：遍历 chain 中所有 role，启动前检查是否有对应 agent |
| **bot 离线** — 派活时 bot 不在线 | 任务发了但 bot 没收到 | inbox 持久化保证投递 |
| **server 重启后拓扑丢失** | `_PIPELINE_CONFIG` 内存数据丢失 | `_PIPELINE_CONFIG` 在现有持久化中已有保留（`persistence.save/load_pipeline_config`），重启后从持久化恢复 |

---

## 6. R88 与 Roadmap 的对应关系

```
Phase 1 — 稳定 Inbox ✅
       ↓
Phase 2 — 自动化管线（进行中）
       ├── ✅ R87: `_inbox:server` 中继架构
       ├── 🔄 **R88: Pipeline AutoRouter** ← 当前轮次
       ├── 🔲 R89: 异常回退 + 并行拓扑
       ├── 🔲 R90: 结构化 Task Card / 监控增强
       └── 🔲 R91: 跨轮次连续工作
       ↓
Phase 3 — Coder Agent 编码专精（待启动）
```

---

## 7. 完整端到端场景

### 场景：6-Step 管线全线自动接力

```
准备工作（Step 1 — PM）：
  ① 写 R88-product-requirements.md
  ② 写 WORK_PLAN.md（含 pipeline.topology 定义）
  ③ 推 dev
  ④ 执行 !pipeline_start R88 --work_plan_url <raw_url>

Server 收到 !pipeline_start：
  ⑤ 解析 frontmatter → _PIPELINE_CONFIG[R88]
  ⑥ 创建 workspace
  ⑦ 发现 auto_chain=true → 读取 chain[0] (step2/architect)
  ⑧ AutoRouter: 派活 Step 2 到 _inbox:arch
  ⑨ 日志: "[R88] Step 1 完成 → 自动派活 Step 2 (architect)"

Step 2（arch — 自动触发）：
  ⑩ arch 收活 → ACK ✅ → 写技术方案 → 推 dev → ✅ 完成
  ⑪ Server 转发 + 自动确认（R87 逻辑）
  ⑫ AutoRouter: chain[0]→chain[1] → 派活 Step 3 到 _inbox:dev

Step 3→4→5→6（自动接力，同上模式）：
  ⑬ 每步自动完成 → 自动转下步

终局：
  ⑭ Step 6 ops ✅ 完成
  ⑮ AutoRouter 发现 chain 终点 → 发「全部完成」通知 PM
  ⑯ PM 收到 🏁 R88 全线闭环
```

**PM 全程操作：** 写文档 → `!pipeline_start` → 收通知 → 收完工。

**Bot 全程感知：** 和现在的流程一样 — 收消息 → ACK → 干活 → ✅ 完成。从 `from_name` 知道是 server 发的（"系统(管线)"），但行为完全不变。

---

## 8. 脱敏检查清单

- [ ] docs/R88/*.md 零内部名残留（frontmatter 的角色 mapping 除外）
- [ ] 使用通用角色名（PM / arch / dev / review / qa / operations）
- [ ] 不包含真实 agent_id / token / URL
- [ ] chain 示例中的 bot 名称用角色名（architect / developer 等），不使用具体 bot 名
