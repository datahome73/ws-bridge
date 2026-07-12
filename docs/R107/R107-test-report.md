# R107 测试报告 — 消除重复代码 + 自动派活功能落地（代码完成，不通电）🔌

> **测试人：** 🦐 泰虾 (QA)
> **测试基准：** `118b74f` → `1a76c2c`
> **测试日期：** 2026-07-13
> **改动范围：** 7 文件，+919/-189 行
>   - `server/main.py`（核心：dedup + _render_template + _auto_dispatch + _get_step_agent_name）
>   - `server/pipeline_context.py`（4 新字段 + 序列化）
>   - `server/config.py`（AUTO_DISPATCH_ENABLED 默认关闭）
>   - `tests/test_r107_render.py`（8 项单元测试）
>   - `docs/R107/` + `docs/pipeline-message-templates.md`

---

## 测试结果

| 测试类别 | 通过 | 失败 | 通过率 |
|:---------|:----:|:----:|:------:|
| 源码验证 | 32 | 0 | **100%** |
| 单元测试（render） | 8 | 0 | **100%** |
| **合计** | **40** | **0** | **100%** |

---

## 验收标准逐项验证

### 1️⃣ `_handle_server_relay` 只有一份 🟢

| 检查项 | 结果 | 证据 |
|:-------|:----:|:------|
| `def _handle_server_relay` 数量 | 🟢 **1 份** | `grep -c` 返回 1 |
| 删除副本后调用方不受影响 | 🟢 | 同一函数名，签名不变 |
| 所有前缀规则保留 | 🟢 | `收到✅`/`已完成✅`/`退回🔄`/`失败❌`/`!`/`test✅` 全在 |

### 2️⃣ Pipeline Context 4 新字段序列化正确 🟢

| 字段 | 类型 | 默认值 | 源码 | 序列化 |
|:-----|:------|:--------|:-----|:------:|
| `round_title` | `str` | `""` | `self.round_title` | `if self.round_title else {}` |
| `references` | `dict` | `{}` | `self.references` | `if self.references else {}` |
| `artifacts` | `dict` | `{}` | `self.artifacts` | `if self.artifacts else {}` |
| `message_templates` | `dict` | `{}` | `self.message_templates` | `if self.message_templates else {}` |

`to_dict()` 跳空字段，旧 context 反序列化兼容。

### 3️⃣ `_render_template` 正确渲染 🟢

8 项单元测试全部通过：

| # | 测试项 | 结果 |
|:-:|:-------|:----:|
| 1 | 基本 round 变量（`{round}`、`{round_title}`） | 🟢 |
| 2 | 引用 URL（`{requirements_url}`、`{work_plan_url}`） | 🟢 |
| 3 | artifacts 变量覆盖 | 🟢 |
| 4 | 多 step artifacts | 🟢 |
| 5 | 真实 Step3 模板渲染 | 🟢 |
| 6 | 空模板（返回空字符串） | 🟢 |
| 7 | 无匹配变量（原样保留） | 🟢 |
| 8 | 未填充变量不变 | 🟢 |

### 4️⃣ `_auto_dispatch` 存在且可调用 🟢

```python
async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:
```

被 `_try_advance_pipeline` 通过 `asyncio.ensure_future(_auto_dispatch(ctx, next_step))` 调用。

### 5️⃣ 开关关闭时不发消息 🟢

```python
AUTO_DISPATCH_ENABLED: bool = os.environ.get("AUTO_DISPATCH_ENABLED", "0") == "1"
```

| 场景 | 行为 |
|:-----|:------|
| 开关关闭（默认） | 日志 `[R107] 自动派活已关闭，跳过 step{X} 发送` + 模拟渲染日志 + `return False` |
| 开关打开 | 执行 `_send_to_agent()` 实际发送 |

### 6️⃣ 无上下文不执行 🟢

`_try_advance_pipeline` 中：
```python
ctx = mgr.get(round_name)
if not ctx:
    logger.info("[R106] 管线 %s 无上下文，跳过自动推进", round_name)
    return False, "no context"
```

无 Pipeline Context 时既不推进也不派活。

### 7️⃣ 最后一步标记 completed 🟢

```python
if next_step <= ctx.total_steps:
    asyncio.ensure_future(_auto_dispatch(ctx, next_step))
else:
    # 最后一步已完成，标记管线 completed
    asyncio.ensure_future(mgr.transition_to(round_name, PipelineStatus.COMPLETED))
    logger.info("[R107] %s 全管线已完成 ✅", round_name)
```

超过 `total_steps` 时 `transition_to(COMPLETED)`。

### 8️⃣ 多轮次并发隔离 🟢

所有函数均以 `round_name`（字符串）为 key 操作 PipelineContextManager，天然隔离。每个轮次的 context 独立存储，`get(round_name)` 只返回指定轮次。

### 9️⃣ 开关关闭时 PM 操作不受影响 🟢

`_handle_server_relay` 中所有前缀匹配逻辑完全不变：

| 前缀 | 行为 | 受开关影响？ |
|:-----|:------|:------------:|
| `收到 ✅` | 转发 PM | ❌ 无影响 |
| `已完成 ✅` | 转发 PM + 自动确认 + 自动推进 | ❌ 无影响（仅推进，派活受开关控制） |
| `退回 🔄` | 转发 PM + 记录 | ❌ 无影响 |
| `失败 ❌` | 转发 PM + 记录 | ❌ 无影响 |
| `!` | 透传 | ❌ 无影响 |
| `test ✅` | 回路测试 | ❌ 无影响 |

---

## 单元测试

| 文件 | 结果 |
|:-----|:----:|
| `tests/test_r107_render.py`（8 项） | 🟢 全部通过 |

---

## 语法

| 文件 | 结果 |
|:-----|:----:|
| `main.py` | 🟢 |
| `pipeline_context.py` | 🟢 |
| `config.py` | 🟢 |

---

## 结论

| 验收项 | 结果 |
|:-------|:----:|
| 1. _handle_server_relay 仅 1 份 | 🟢 |
| 2. 4 新字段序列化 | 🟢 |
| 3. _render_template 渲染 | 🟢 |
| 4. _auto_dispatch 可调用 | 🟢 |
| 5. 开关关闭不发送 | 🟢 |
| 6. 无上下文不执行 | 🟢 |
| 7. 最后一步 completed | 🟢 |
| 8. 多轮次隔离 | 🟢 |
| 9. 开关关闭无行为变化 | 🟢 |
| **最终结论** | **🟢 可合并** |

R107 消除重复代码 + 自动派活功能落地完成。`_handle_server_relay` 从 2 份减为 1 份（净删 ~200 行），新增 `_render_template`、`_auto_dispatch`、`_get_step_agent_name`，Pipeline Context 新增 4 字段。自动派活受 `AUTO_DISPATCH_ENABLED` 控制（默认关闭），代码完整但不通电。40/40 🟢 通过。

---

*报告编写: 🦐 泰虾 · 2026-07-13*
