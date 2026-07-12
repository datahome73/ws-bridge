# R107: 消除重复代码 + 自动派活功能落地（代码完成，不通电）

> **版本：** v1.0
> **日期：** 2026-07-13
> **状态：** 📝 需求文档
> **轮次：** R107（即 R106b）
> **前置条件：** R106a 已闭环 ✅

---

## 一、背景

### 1.1 R106 回顾

R106a 完成了两件事：
- Pipeline Context 状态自动推进
- `!pipeline_status` 增强

但自动派活的核心功能还没写——`_render_template`（模板渲染）、`_auto_dispatch`（自动发送）这些函数还没实现。Pipeline Context 也缺了 `round_title/references/artifacts/message_templates` 4 个字段。

**本轮只装最后一个轮子，不点火。**

### 1.2 当前问题

| # | 问题 | 影响 |
|:-:|:-----|:------|
| 1 | **`_handle_server_relay` 两份重复代码** | 两份各 ~200 行的完全相同的函数（L2424 & L2628），维护成本高，容易漏改 |
| 2 | **无自动派活代码** | `_render_template`、`_auto_dispatch` 这两个核心函数不存在 |
| 3 | **Pipeline Context 缺字段** | `round_title`、`references`、`artifacts`、`message_templates` 4 个字段未添加到 dataclass |
| 4 | **无变量填充机制** | 消息模板中的 `{commit_sha}`、`{file_changes}` 等变量无法自动填充 |

---

## 二、目标

### 2.1 本轮目标

1. **消除重复代码** — 将两副本 `_handle_server_relay` 抽取为单一共享函数
2. **Pipeline Context 字段补全** — 添加 `round_title/references/artifacts/message_templates`
3. **完成自动派活代码** — 实现 `_render_template` + `_auto_dispatch`，写好全部代码逻辑
4. **预留开关** — 自动派活代码写完后 **通过配置/常量关闭实际发送**，本轮不接通

### 2.2 下轮（R108）目标

启用自动派活开关，跑一次全自动流水线验证。

### 2.3 本轮成功标准

- `_handle_server_relay` 只有 **一份** 代码 ✓
- Pipeline Context 4 新字段可创建、可序列化、可读取 ✓
- `_render_template` + `_auto_dispatch` 函数存在且可被调用 ✓
- 自动派活开关默认关闭，**不实际发出消息** ✓
- 结束前通过上下文检查确认管线数据结构完整 ✓

---

## 三、详细需求

### 3.1 消除 `_handle_server_relay` 重复代码

**现状：**

| 副本 | 起始行 | 代码量 |
|:-----|:-------|:------:|
| 副本 1 | L2424 | ~200 行 |
| 副本 2 | L2628 | ~200 行 |

两副本内容完全相同。

**方案：**

1. 保留副本 1（L2424），删除副本 2（L2628-L2830）
2. 在副本 2 原调用处改为调用副本 1
3. 确保两个原始调用点的行为完全一致

**变更：**
- `server/main.py` — 净删 ~200 行

### 3.2 Pipeline Context 字段补全

在 `server/pipeline_context.py` 的 `PipelineContext` dataclass 中新增 4 个字段：

```python
@dataclass
class PipelineContext:
    # ... 现有字段 ...
    round_title: str = ""                        # 人类可读标题
    references: dict = field(default_factory=dict)  # 文档 URL
    artifacts: dict = field(default_factory=dict)   # 每步产出 KV
    message_templates: dict = field(default_factory=dict)  # 派活模板
```

| 字段 | 类型 | 默认值 | 用途 |
|:-----|:------|:--------|:------|
| `round_title` | `str` | `""` | 轮次标题，如 `"Pipeline Context + Step 自动推进"` |
| `references` | `dict` | `{}` | 文档 URL，至少含 `requirements_url` / `work_plan_url` |
| `artifacts` | `dict` | `{}` | 每步产出 KV，如 `{"step3": {"commit_sha": "abc1234"}}` |
| `message_templates` | `dict` | `{}` | 派活模板，如 `{"step2": "📋 R{round} Step 2 ..."}` |

**必须同步更新：**
- `to_dict()` — 4 字段序列化
- `from_dict()` — 反序列化
- `to_dict()` 中 **跳过空字段**（`""` / `{}`）以保持向后兼容

**变更：**
- `server/pipeline_context.py` — +15 行

### 3.3 自动派活功能（代码完成，默认关闭）

#### 3.3.1 开关设计

在 `server/config.py` 中增加配置常量：

```python
# R107: 自动派活开关 — 默认关闭，R108 再开启
AUTO_DISPATCH_ENABLED: bool = False
```

或使用环境变量：
```python
AUTO_DISPATCH_ENABLED: bool = os.environ.get("AUTO_DISPATCH_ENABLED", "0") == "1"
```

所有自动派活逻辑在开关关闭时**不执行任何发送操作**，仅记录日志：
```python
if not config.AUTO_DISPATCH_ENABLED:
    logger.info("[R107] 自动派活已关闭（AUTO_DISPATCH_ENABLED=False），跳过实际发送")
    # 仅记录日志，不执行 _send_to_agent
```

#### 3.3.2 消息渲染函数 `_render_template()`

```python
def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str:
    """用 Pipeline Context 数据渲染模板字符串。"""
    vars = {
        "round": ctx.round_name,
        "round_title": ctx.round_title,
        "requirements_url": ctx.references.get("requirements_url", ""),
        "work_plan_url": ctx.references.get("work_plan_url", ""),
    }
    # 补充来自 artifacts 的变量（覆盖同名变量）
    for step_key, step_artifacts in ctx.artifacts.items():
        if isinstance(step_artifacts, dict):
            vars.update(step_artifacts)
    # 填充模板中的 {var} 占位符
    for key, value in vars.items():
        template = template.replace(f"{{{key}}}", str(value))
    return template
```

#### 3.3.3 自动派活函数 `_auto_dispatch()`

```python
async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:
    """自动派活下一步。受 AUTO_DISPATCH_ENABLED 开关控制。"""
    if not config.AUTO_DISPATCH_ENABLED:
        logger.info("[R107] 自动派活已关闭，跳过 step%d 发送 (round=%s)", step_num, ctx.round_name)
        # 模拟：仅打印渲染结果，不实际发送
        next_step_key = f"step{step_num}"
        next_template = ctx.message_templates.get(next_step_key, "")
        if next_template:
            rendered = _render_template(next_template, ctx, step_num)
            logger.info("[R107] [模拟] 将派活 step%d 给 %s:\n%s", 
                        step_num, 
                        _get_step_agent_name(ctx, step_num),
                        rendered)
        return False
    
    # ← 实际发送逻辑（开关打开后才执行）
    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key)
    if not next_template:
        logger.warning("[R107] 管线 %s 缺少 step%d 模板，跳过自动派活", ctx.round_name, step_num)
        return False
    
    next_step_info = next((s for s in ctx.steps if s.get("name") == next_step_key), None)
    if not next_step_info or not next_step_info.get("agent_id"):
        logger.warning("[R107] 管线 %s step%d 无 agent_id，跳过自动派活", ctx.round_name, step_num)
        return False
    
    target_agent_id = next_step_info["agent_id"]
    content = _render_template(next_template, ctx, step_num)
    
    payload = {
        "type": "message",
        "channel": "_inbox:server",
        "content": content,
        "from_name": "小谷",
        "agent_id": "ws_f26e585f6479",
        "to_agent": target_agent_id,
        "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time()*1000)}",
        "ts": time.time(),
    }
    
    sent = await _send_to_agent(target_agent_id, payload)
    return sent > 0


def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str:
    """辅助函数：获取指定 step 的 agent 名称。"""
    step_key = f"step{step_num}"
    info = next((s for s in ctx.steps if s.get("name") == step_key), None)
    if info:
        return info.get("agent_name", info.get("agent_id", "?"))
    return "?"
```

#### 3.3.4 在 `_try_advance_pipeline` 中的插入位置

在 `_try_advance_pipeline()` 成功推进 step 后、返回前，插入：

```python
# ── R107: 自动派活下一步 ──
if advance_success:
    next_step = old_step + 1  # 推进后的当前 step
    if next_step <= ctx.total_steps:
        asyncio.ensure_future(_auto_dispatch(ctx, next_step))
    else:
        # 最后一步已完成，标记管线 completed
        ctx.status = PipelineStatus.COMPLETED
        logger.info("[R107] %s 全管线已完成 ✅", round_name)
```

**注意：** `_try_advance_pipeline()` 原函数签名是同步的（不带 async），但 `_auto_dispatch()` 是 async 的。两种处理方式：

| 方案 | 做法 | 推荐 |
|:-----|:------|:----:|
| 🅰 `asyncio.ensure_future` | 从同步函数中启动 async 协程 | ✅ 推荐（改动最小） |
| 🅱 改为 async | 整个函数改为 async def | 改动大，调用处都要变 |

**推荐 🅰**：`asyncio.ensure_future(_auto_dispatch(ctx, next_step))`

#### 3.3.5 自动派活触发时机（预留）

| 完成步骤 | 下一步目标 | 开关打开后的效果 |
|:---------|:-----------|:-----------------|
| Step 1 (PM) | → Step 2 (arch) | 自动派给小开 |
| Step 2 (arch) | → Step 3 (dev) | 自动派给爱泰 |
| Step 3 (dev) | → Step 4 (review) | 自动派给小周 |
| Step 4 (review) | → Step 5 (qa) | 自动派给泰虾 |
| Step 5 (qa) | → Step 6 (ops) | 自动派给小爱 |
| Step 6 (ops) | → 管线完成 | 标记 completed |

> ⚠️ **本轮不启用**，所有派活行为受 `AUTO_DISPATCH_ENABLED=False` 控制。

### 3.4 不需要改动的

| 项目 | 原因 |
|:-----|:------|
| 回复格式协议 | 已就位（R105） |
| 前端模板 | 纯后端改动 |
| Web 服务 | 无关 |
| 认证/权限 | 无关 |
| Bot 客户端 | Server 端改动，bot 无感知 |

---

## 四、变更文件清单

| 文件 | 改动 | 估算 |
|:-----|:------|:-----|
| `server/config.py` | 新增 `AUTO_DISPATCH_ENABLED` 常量 | +3 行 |
| `server/main.py` | 删除 `_handle_server_relay` 副本 2（~200 行）；增加 `_render_template` + `_auto_dispatch` + `_get_step_agent_name`（~70 行）；`_try_advance_pipeline` 中插入 `_auto_dispatch` 调用 + 最后一步 completed（~15 行） | **-115 行** |
| `server/pipeline_context.py` | 新增 4 字段 + to_dict/from_dict 同步 | +15 行 |
| **总计** | | **~-97 行（净减）** |

---

## 五、验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `_handle_server_relay` 只有一份代码 | `grep -c "async def _handle_server_relay" server/main.py` 返回 1 |
| 2 | Pipeline Context 4 新字段正确序列化/反序列化 | 创建→to_dict→from_dict→读取，字段值不变 |
| 3 | `_render_template` 正确渲染模板 | 传入模板 + examples ctx，检查 `{round}` `{commit_sha}` 等变量被正确替换 |
| 4 | `_auto_dispatch` 存在且可被调用 | 函数在 main.py 中可 import / 被引用 |
| 5 | `AUTO_DISPATCH_ENABLED=False` 时不实际发消息 | 日志打印 `[R107] 自动派活已关闭`，不执行 `_send_to_agent` |
| 6 | 无 Pipeline Context 时不执行任何自动派活逻辑 | 旧消息格式不受影响 |
| 7 | 最后一步完成后标记 completed | `ctx.status` 变为 `"completed"` |
| 8 | 多轮次并发隔离 | round_name 隔离，互不干扰 |
| 9 | 开关关闭时 PM 管线操作不受任何影响 | 手工派活照常工作，无延迟/异常 |

---

## 六、风险与注意事项

| 风险 | 等级 | 缓解 |
|:-----|:-----|:------|
| 删除副本 2 后漏调 | 🔴 | 删除后 `grep -n "_handle_server_relay" server/main.py` 确认零引用 |
| 开关关闭但仍有发送 | 🟡 | 代码中所有发送路径都受 `AUTO_DISPATCH_ENABLED` 保护 |
| 同步函数启动 async 协程 | 🟢 | `asyncio.ensure_future()` 标准用法，Hermes 事件循环中安全 |
| to_dict 向后兼容 | 🟢 | 空字段跳过，旧 context 反序列化不受影响 |
| 合并 dev→main 冲突 | 🟡 | R106a 刚合入 dev，main 仍为 R105 代码 |

---

## 七、本轮结束状态检查

R107 完成后的检查项（**不跑全自动流水线**）：

1. ✅ `_handle_server_relay` 已合并为单份
2. ✅ Pipeline Context 4 新字段可用
3. ✅ `_render_template` 可正常渲染
4. ✅ `_auto_dispatch` 代码完整，受开关保护
5. 🔲 **下轮 R108：** 设置 `AUTO_DISPATCH_ENABLED=True`，跑一次全 6 步流水线验证

---

## 附录：模板变量一览

| 变量 | 来源 | 示例 |
|:-----|:------|:------|
| `{round}` | `ctx.round_name` | `R107` |
| `{round_title}` | `ctx.round_title` | `消除重复代码 + 自动派活` |
| `{requirements_url}` | `ctx.references` | `https://raw.githubusercontent.com/.../R107-product-requirements.md` |
| `{work_plan_url}` | `ctx.references` | `https://raw.githubusercontent.com/.../WORK_PLAN.md` |
| `{task_description}` | `ctx.artifacts.step2` | `评估...` |
| `{file_changes}` | `ctx.artifacts.step3` | `server/main.py — -200/+80 行` |
| `{commit_sha}` | `ctx.artifacts.step3` | `abc1234` |
| `{files_list}` | `ctx.artifacts.step3` | `server/main.py, server/pipeline_context.py` |
| `{acceptance_criteria}` | 需求文档摘要 | 验收项逐项 |
| `{deploy_instructions}` | `ctx.artifacts.step2` | `合并 dev→main，docker build` |

> 所有变量通过 `_render_template()` 统一填充。未填到的变量保留 `{var}` 原文。
