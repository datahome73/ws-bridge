# R90 产品需求 — AutoRouter 坑位修补 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R89 AutoRouter 增强已部署 ✅（v2.55, main `0a6d2e4`）
> **改动范围：** `server/auto_router.py` + `handler.py`（最小侵入）

---

## 1. 问题背景

### 1.1 现状

R88 → R89 实现了 AutoRouter 自动派活 + 超时检测，R89 实战走通了一个完整 Pipeline 闭环。但在实战中发现三个问题：

| # | 问题 | 影响 | 发现轮次 |
|:-:|:-----|:-----|:---------|
| 🅰️ | AutoRouter 监听范围不足 — 只监听 PM 收件箱，`!pipeline_start` 响应走 `_admin` | AutoRouter 无法自动检测管线就绪 | R89 Step 1 |
| 🅱️ | 工作区创建失败不阻断管线启动 — 但 AutoRouter 不知晓管线存在 | 管线静默不自动接力，PM 需手动 inbox 协调全流程 | R89 Step 1 |
| 🅲 | `STEP_TIMEOUT=0` 禁用超时未实现 | R89 审查 🟡 条件通过，待 R90 补 | R89 Step 4 |

### 1.2 问题 🅰️ 详解：AutoRouter 监听范围不足

AutoRouter 当前只监听 PM 收件箱 (`_pm_inbox_channel`)，通过 R87 中继接收 `_inbox:server` 转发的通知：

```python
# auto_router.py 第 166 行
if self._pm_inbox_channel and channel != self._pm_inbox_channel:
    return
```

但 `!pipeline_start` 的响应消息走 `_admin` 频道：

```python
# handler.py _cmd_pipeline_start 返回值
return (
    f"🚀 **{round_name} 管线已启动**\n"
    ...
)
```

这条消息 → `_admin`（命令发起的频道），**不经 R87 中继转发**，所以 PM 收件箱收不到 → AutoRouter 检查 `channel != self._pm_inbox_channel` 时静默丢弃。

**根本原因：** AutoRouter 部署时设计为「以 bot 身份监听 PM 收件箱」，但 `!pipeline_start` 的服务端响应不经过 inbox 通道。

### 1.3 问题 🅱️ 详解：工作区创建失败

R89 实战中 `!pipeline_start` 的返回包含：

```
🚀 R89 管线已启动
  Step: step2 → architect
  工作室: ws_r89-dev
  ❌ 创建失败：R89-dev 可能已存在，或管理员名下活跃工作区过多
  ✅ Task 已创建：step2 (submitted)
```

管线 `_PIPELINE_CONFIG` 和 Task 已创建成功，但：
- 工作区未成功创建或关联
- Task 创建在空壳管线中
- `!pipeline_status R89` 返回 ❌ 管线不存在
- AutoRouter 从未收到信号

**问题根因有多个可能：**
1. 活跃工作区数量超限（管理员名下有 2 个活跃+归档工作区）
2. 命名冲突（已有一个包含 `R89` 的旧工作室残留）
3. thread_name_for_round 命名规则重叠

### 1.4 问题 🅲 详解：`STEP_TIMEOUT=0` 未实现

R89 审查 🟡 条件通过指出：PRD 写了 `STEP_TIMEOUT=0` 可禁用超时检测，但实际代码中 `_STEP_DEFAULT_TIMEOUT` 是硬编码类常量：

```python
_STEP_DEFAULT_TIMEOUT = 7200  # 2 小时默认超时
```

如果用户设 = 0，`elapsed > 0` 恒真 → 所有 Step 立即标记超时。

---

## 2. 方案设计

### 2.1 改动范围

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `server/auto_router.py` | 🅰️ 监听 `_admin` 信号 + 🅲 `AR_STEP_TIMEOUT` 环境变量 | ~+40 行 |
| `server/handler.py` | 🅱️ 工作区创建失败时通知 PM 收件箱 | ~+15 行 |
| **合计** | | **~+55 行净增** |

**零修改：** `config.py` ✅ · `__main__.py` ✅ · `shared/` ✅ · `tests/` ✅

### 2.2 🅰️ AutoRouter 增加 admin 频道监听

**原理：** AutoRouter 从「只监听 PM 收件箱」改为「主要监听 PM 收件箱 + 也监听 `_admin` 频道的管线启动信号」。

**改动：** `_handle_message()` 增加 `_admin` 信号检测通道：

```python
# 在现有 PM inbox 检查之后增加 admin 频道检查
async def _handle_message(self, msg: dict) -> None:
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()
    msg_id = msg.get("id", "")

    if self._mark_seen(msg_id):
        return

    # ── 通道过滤 ──
    is_pm_inbox = self._pm_inbox_channel and channel == self._pm_inbox_channel
    is_admin = channel == "_admin"

    if not is_pm_inbox and not is_admin:
        return  # 只处理 PM inbox 或 _admin 的消息

    # ═══ 信号 1: 管线就绪 ═══
    if "管线已启动" in content:
        round_name = self._extract_round(content)
        if round_name:
            await self._on_pipeline_ready(round_name)
        return

    # ═══ PM inbox: Step 完成信号等（R87 中继转发） ═══
    if is_pm_inbox:
        if content.startswith("✅ ") and "任务完成" in content:
            await self._on_step_complete(content)
            return
        if content.startswith("✅ 完成") or "✅ 完成，已推" in content:
            await self._on_step_complete(content)
            return
```

**需要精确定义的信号匹配规则：**

| 通道 | 信号 | AutoRouter 行为 |
|:-----|:------|:----------------|
| `_admin` | `🚀 **R90 管线已启动**` | 解析 round_name → `_on_pipeline_ready()` |
| `_admin` | 其他内容 | 忽略（不干扰 admin 频道正常通信） |
| PM inbox | ✅ 完成 / ACK 转发 | 现有 R87 中继处理（不变） |

**去重：** `_mark_seen(msg_id)` 已覆盖 admin 频道的消息 ID。

### 2.3 🅱️ 工作区创建失败时通知 PM 收件箱

**原理：** `_cmd_pipeline_start()` 在返回时，如果 `create_result` 包含 `❌`（失败标记），同时发送一条通知到 PM 收件箱。

**改动点：** handler.py 的 `_cmd_pipeline_start()` 末尾（L2822 附近），在 return 之前增加：

```python
# ── R90 🅱️: 工作区创建失败通知 PM ──
if "❌" in create_result:
    pm_inbox = persistence.get_inbox_channel(pm_id)
    if pm_inbox:
        await _broadcast_to_channel(pm_inbox, {
            "type": "broadcast", "channel": pm_inbox,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": (
                f"⚠️ {round_name} 管线已启动但工作区创建失败。\n"
                f"请手动确认工作区状态或使用 --workspace-id 指定现有工作区。\n"
                f"AutoRouter 可能无法自动接力，建议检查后手动启动。"
            ),
            "ts": time.time(),
        })
```

**目标：** 工作区创建失败时 PM 收件箱能收到告警 → AutoRouter 如果能监听 `_admin`（🅰️ 修复），此通知是额外保底。

### 2.4 🅲 `AR_STEP_TIMEOUT` 环境变量 + `STEP_TIMEOUT=0` 守卫

**原理：** 将硬编码 `_STEP_DEFAULT_TIMEOUT = 7200` 改为从环境变量 `AR_STEP_TIMEOUT` 读取，并增加 `<= 0` 守卫。

**改动点：**

```python
# 常量
_STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))
# R90 🅲: <= 0 时禁用超时检测
_STEP_TIMEOUT_ENABLED = _STEP_DEFAULT_TIMEOUT > 0
```

**`_check_step_timeouts()` 增加守卫：**

```python
async def _check_step_timeouts(self) -> None:
    if not self._STEP_TIMEOUT_ENABLED:
        return  # R90 🅲: 超时检测已禁用
    ...
```

**`_timeout_check_loop()` 增加守卫：**

```python
async def _timeout_check_loop(self) -> None:
    if not self._STEP_TIMEOUT_ENABLED:
        logger.info("[AR] ⏰ 超时检测已禁用 (AR_STEP_TIMEOUT<=0)")
        return  # 直接退出，不启动定时器
    ...
```

**`__init__()` 增加日志：**

```python
logger.info("[AR] 超时=%ds (%s)", self._STEP_DEFAULT_TIMEOUT,
    "启用" if self._STEP_TIMEOUT_ENABLED else "禁用")
```

**同时修补 `_timeout_check_loop()` 中 timer 的启动位置：** 移到 `_STEP_TIMEOUT_ENABLED` 守卫之后。

### 2.5 向后兼容

| 场景 | 影响 | 说明 |
|:-----|:-----|:------|
| 不设 `AR_STEP_TIMEOUT` | ✅ 无 | 默认 7200，行为不变 |
| `AR_STEP_TIMEOUT=0` | ✅ 禁用超时 | 定时器不启动，无性能开销 |
| `AR_STEP_TIMEOUT=3600` | ✅ 1 小时超时 | 环境变量覆盖默认 |
| AutoRouter 旧版 | ✅ 无 | 新版兼容旧版 systemd 配置 |
| handler.py 零改动（不移除） | ✅ 无 | 改动仅 ~15 行新增代码 |
| admin 频道其他消息 | ✅ 无 | 精确匹配 `🚀 **R{round} 管线已启动**` |

---

## 3. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| 🅰️-1 | AutoRouter 处理 `_admin` 频道的 `管线已启动` 消息 | 单元测试：构造 admin 消息 → `_on_pipeline_ready` 被调用 |
| 🅰️-2 | AutoRouter 不处理 `_admin` 频道的其他消息 | 单元测试：无关消息 → 无行为 |
| 🅰️-3 | PM inbox 通道行为不变 | 回归：R87 中继转发 → 正常处理 |
| 🅱️-1 | 工作区创建失败时 PM 收件箱收到 ⚠️ 通知 | 集成测试：模拟 workspace 创建失败 |
| 🅱️-2 | 工作区创建成功时不发通知 | 不干扰正常流程 |
| 🅱️-3 | `create_result` 无 `❌` 时跳过 | 正常 case 零侵入 |
| 🅲-1 | `AR_STEP_TIMEOUT` 环境变量被读取 | 设 env → 构造 → 检查类常量 |
| 🅲-2 | `AR_STEP_TIMEOUT <= 0` 禁用超时 | 设 0 → 定时器不启动 |
| 🅲-3 | `AR_STEP_TIMEOUT` 未设时默认 7200 | 无 env → 默认值 |
| 🅲-4 | 超时禁用时日志正确 | INFO 日志「超时检测已禁用」 |
| 🅲-5 | `_check_step_timeouts()` 有 `<=0` 守卫 | 守卫行存在 |
| 🅲-6 | `_timeout_check_loop()` 有 `<=0` 守卫 | 守卫行存在 |

---

## 4. R90 管线 Step 定义

```
Step 1: PM — 写入该需求文档 + WORK_PLAN → 推 dev
Step 2: Arch — 技术方案（含 3 处改动设计）
Step 3: Dev — 编码实现（auto_router.py ~+40 行 + handler.py ~+15 行）
Step 4: Review — 代码审查（重点：admin 频道监听安全、env vars 集成）
Step 5: QA — 测试验证（12 项验收）
Step 6: Ops — 合并部署（main merge + docker build + 重启 AutoRouter）
```

---

## 5. 风险与缓解

| 风险 | 等级 | 缓解 |
|:-----|:----:|:------|
| AutoRouter 监听 `_admin` 后被大量无关消息刷屏 | 🟢 | `_mark_seen()` 去重 + 精确信号匹配 `🚀 **R{round} 管线已启动**` |
| handler.py 侵入增加回归风险 | 🟡 | 改动控制在 `_cmd_pipeline_start` 末尾 ~15 行，不修改任何现有逻辑路径 |
| `AR_STEP_TIMEOUT` 拼写错误 | 🟢 | 默认值 7200，环境变量缺失时退化为默认 |
| AutoRouter 同时收到 admin 和 inbox 两条相同信号 | 🟢 | `_mark_seen(msg_id)` 去重保证幂等 |
