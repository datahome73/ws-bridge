# R90 代码审查报告 — AutoRouter 坑位修补 🔧

> **审查人：** 🔍 小周
> **审查基准：** `2593688` (R89) → `b21103a` (R90)
> **改动文件：** `server/auto_router.py` (+61/-23) · `server/handler.py` (+23/-0)
> **参考文档：**
> - 技术方案: `docs/R90/R90-tech-plan.md`
> - 产品需求: `docs/R90/R90-product-requirements.md`
> - WORK_PLAN: `docs/R90/WORK_PLAN.md`

---

## 审查结论：🟢 通过

4/4 检查项全部通过，无阻断性问题。

---

## 🅰️ AutoRouter _admin 频道监听安全

**判定：🟢 通过**

**改动：** `_handle_message()` 入口过滤从"单频道"改为"白名单双频道"。

### 白名单设计

```python
# 入口过滤
is_pm_inbox = self._pm_inbox_channel and channel == self._pm_inbox_channel
is_admin = channel == "_admin"
if not is_pm_inbox and not is_admin:
    return  # 只处理 PM inbox 或 _admin 的消息
```

| 频道 | 允许的信号 | 拒绝的信号 |
|:-----|:-----------|:-----------|
| `_inbox:<PM_id>` | 管线启动 + Step 完成 | 无（全处理） |
| `_admin` | 管线启动（含 "管线已启动"） | Step 完成（`if is_admin: return`） |
| 其他 | 全部拒绝 | 入口即拦截 |

### 安全分析

| 风险 | 评估 | 缓解 |
|:-----|:-----|:------|
| `_admin` 噪音触发误处理 | 🟢 低 | 信号匹配 `"管线已启动"` 非常具体，误触极低 |
| Step 完成从 `_admin` 混入 | 🟢 低 | `if is_admin: return` 显式拦截非管线启动信号 |
| 重复信号（PM inbox + _admin 各一份） | 🟢 低 | `_mark_seen` 去重 + `_on_pipeline_ready` 幂等覆盖 |
| 非 R90 旧代码行为变化 | 🟢 无 | 白名单包含了原有 `_pm_inbox_channel`，旧路径完整保留 |

### 流程验证

```
!pipeline_start → handler._cmd_pipeline_start()
  │
  ├─ 响应走 _admin 频道 ──→ AutoRouter._handle_message()
  │   通道: _admin → is_admin = True
  │   内容: "🚀 **R90 管线已启动**..." → "管线已启动" in content ✓
  │   动作: _on_pipeline_ready("R90")
  │
  └─ R87 中继走 PM inbox ──→ AutoRouter._handle_message()
      通道: _inbox:<PM_id> → is_pm_inbox = True
      同上管线启动信号 → _on_pipeline_ready("R90") [幂等]
```

---

## 🅲 AR_STEP_TIMEOUT 环境变量集成

**判定：🟢 通过**

**改动：** `_STEP_DEFAULT_TIMEOUT` 从硬编码类常量改为 `os.environ.get()`，并增加 `<=0` 守卫。

### 集成结构

| 代码位置 | 作用 | 状态 |
|:---------|:-----|:-----|
| L39 | `_STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))` | ✅ 环境变量读取 |
| L40 | `_STEP_TIMEOUT_ENABLED = _STEP_DEFAULT_TIMEOUT > 0` | ✅ <=0 守卫 |
| L93-97 | `__init__()` 日志输出启用/禁用状态 | ✅ 可观测性 |
| L162-169 | `_connect_and_listen()` 条件创建超时 task | ✅ 禁用时不启动 |
| L424-427 | `_timeout_check_loop()` 入口守卫 | ✅ 双重保险 |
| L442-444 | `_check_step_timeouts()` 入口守卫 | ✅ 三重保险 |

### 守卫验证

| 场景 | `AR_STEP_TIMEOUT` 值 | `_STEP_TIMEOUT_ENABLED` | 行为 |
|:-----|:--------------------:|:-----------------------:|:-----|
| 默认 | 未设置 / "7200" | `True` | 超时 2h，正常检测 |
| 禁用 | "0" | `False` | 不创建 task，不触发 |
| 禁用（负值） | "-1" | `False` | 同 0，禁用 |
| 自定义时长 | "3600" | `True` | 超时 1h |
| 非法值 | "abc" | `ValueError` → 启动时崩溃 | 配置错误，fail-fast 合理 |

⚠️ **注意：** 环境变量在类定义时（模块加载时）读取一次，运行时修改不生效。这属于标准 Python 行为，可接受。

---

## 🅱️ handler.py 工作区失败通知

**判定：🟢 通过**

**改动：** `_cmd_pipeline_start()` 末尾（return 前）增加工作区创建失败的通知逻辑。

### 安全集成验证

| 检查项 | 状态 | 证据 |
|:-------|:----:|:------|
| 零侵入 — 不修改已有流程 | ✅ | 代码追加在 `_cmd_pipeline_start` 最末尾、return 之前 |
| 条件触发 | ✅ | `if pm_agent_id and "❌" in create_result:` |
| 含失败时不报 | ✅ | `"❌"` 不在 `create_result` 中时直接跳过 |
| 异常不崩主线 | ✅ | 整个通知块包裹 `try/except Exception` |
| 使用现有 handler.py 模式 | ✅ | 复用 `_broadcast_to_channel`、`SYSTEM_AGENT_ID` |
| 通知内容清晰 | ✅ | 包含 round_name、create_result、建议动作 |

### 数据流

```
_cmd_pipeline_start()
  │
  ├─ (工作区创建) ... 现有逻辑
  │
  ├─ if "❌" in create_result and pm_agent_id:  ← 🅱️ 新增
  │      _broadcast_to_channel(_inbox:<PM>, 通知消息)
  │      logger.info("R90 🅱️: 已通知 PM")
  │
  └─ return "🚀 R90 管线已启动..." (原有 return 不变)
```

---

## Scope 合规 — 仅 2 文件

**判定：🟢 通过**

| 文件 | 变动 | 净增行 |
|:-----|:-----|:------:|
| `server/auto_router.py` | 3 处改动（admin 白名单 + env var + 守卫） | +44 |
| `server/handler.py` | `_cmd_pipeline_start` 末尾 1 处追加 | +23 |
| **合计** | **2 文件** | **+67 净增** |

**零修改确认：** `config.py` ✅ · `__main__.py` ✅ · `shared/` ✅ · `tests/` ✅

---

## 额外发现

### 代码质量观察

| # | 类型 | 描述 | 建议 |
|:-:|:----:|:-----|:-----|
| 1 | 🟢 风格 | `_timeout_check_loop()` 和 `_check_step_timeouts()` 均有 `_STEP_TIMEOUT_ENABLED` 守卫 | 三重守卫略微冗余但 100% 安全，可保留 |
| 2 | 🟢 细节 | `handler.py` 通知中 `create_result` 包含完整返回值（可能含换行） | PM 可在 inbox 中直接看到原始错误，调试友好 |
| 3 | 🟢 兼容 | handler.py 使用 `getattr(config, "PIPELINE_PM_AGENT_ID", "")`，config 无此属性时正常跳过 | 优雅降级 |

### 与技术方案一致性

| 技术方案条目 | 实现 | 状态 |
|:------------|:-----|:----:|
| 🅰️ `_handle_message` 白名单 + 双频道 | L197-219 | ✅ |
| 🅰️ Step 完成限 PM 收件箱 | L215-218 | ✅ |
| 🅱️ `_cmd_pipeline_start` 末尾加通知 | handler.py L2821-2846 | ✅ |
| 🅲 `AR_STEP_TIMEOUT` 环境变量 | L39 | ✅ |
| 🅲 `<=0` 守卫 | L40 + L162 + L424 + L442 | ✅ |
| 🅲 禁用时日志 | L93-97, L168-169, L426-427 | ✅ |

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:-----|
| 🅰️ _admin 频道监听安全 | 🔴 | 🟢 | 白名单模式，信号精确匹配，Step 完成信号受保护 |
| 🅲 AR_STEP_TIMEOUT 环境变量 + <=0 守卫 | 🔴 | 🟢 | 三明治守卫（入口 + 循环 + 检查），禁用彻底 |
| 🅱️ handler.py 工作区失败通知 | 🔴 | 🟢 | 条件触发 + try/except 保护，不侵入现有流程 |
| Scope 合规（仅 2 文件） | 🟢 | 🟢 | auto_router.py + handler.py 共 +67 行 |
| 与技术方案一致性 | 🟢 | 🟢 | 6/6 条目匹配 |

**最终结论：🟢 通过** — R90 三处改动均安全合规。`_admin` 白名单过滤精确，`AR_STEP_TIMEOUT` 守卫完善，handler.py 通知零侵入。可进入 Step 5 🦐 QA 测试。

---

*报告编写: 🔍 小周 · 2026-07-10*
