---
pipeline:
  name: "R92 AutoRouter 最终修复 — !pipeline_start 广播到 _admin 频道 📡"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92/R92-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 技术方案
      - step: step3
        role: developer
        title: 编码实现
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署 + AutoRouter 全自动管线验证
  steps:
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
      title: 合并部署 + AutoRouter 全自动管线验证
  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "方案设计：_cmd_pipeline_start 广播 + AutoRouter 信号匹配"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码：handler.py ~+14 行 broadcast"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 broadcast 安全、重复消除"
      qa:
        mention_keyword: "qa;测试"
        rules: "验收：全自动管线闭环验证"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 main + docker build + 启动全自动管线验证"
---

# R92 产品需求 — AutoRouter 最终修复 📡

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R91 workspace 修复已部署 ✅（main, `3fee1c5`）
> **改动范围：** `server/handler.py` 仅 1 文件 ~+14 行

---

## 1. 问题背景

### 1.1 现状：三层修复后的 AutoRouter

经过 R88-R91 四次迭代，AutoRouter 的基础能力已经完整：

| # | 轮次 | 修复项 | 状态 |
|:-:|:----:|:-------|:----:|
| 1 | R88 | AutoRouter 独立服务创建 + 拓扑派活 | ✅ 已部署 |
| 2 | R89 | `_send_inbox()` payload 补全 + Step 超时检测 | ✅ 已部署 |
| 3 | R90 🅰️ | AutoRouter 监听 `_admin` 频道的管线启动信号 | ✅ 已部署 |
| 4 | R90 🅱️ | 工作区创建失败通知 PM 收件箱 | ✅ 已部署 |
| 5 | R90 🅲 | `AR_STEP_TIMEOUT` 环境变量 + `<=0` 守卫 | ✅ 已部署 |
| 6 | R91 🅰️ | `max_per_person=1` → `MAX_ACTIVE_WORKSPACES` 默认 3 | ✅ 已部署 |
| 7 | R91 🅱️ | 创建失败错误信息细化（重名/超限区分） | ✅ 已部署 |

但 R91 的 `!pipeline_start R91` 实际测试中，AutoRouter **仍然没有触发** —— 尽管 workspace 创建成功、代码版本正确、WS 连接正常。

### 1.2 根因：`_send` vs `_broadcast_to_channel`

通过 R91 实战 + 小爱逐行排查，确认根因是**消息路由路径断裂**：

```
发命令:   小谷 → _admin 频道
              ↓
处理:     handle_message() → _cmd_pipeline_start()
              ↓
回复:     _send(ws, msg)         ← 只回复发送者（小谷）的 WS 连接
          ❌ 不 broadcast         ← AutoRouter 收不到
              ↓
AutoRouter:  日志空 — 没有任何消息被 _handle_message 接收到
```

**代码确认：** `handle_message()` L5323 处对所有 `!` 命令调用 `_send_cmd_response()`，后者只执行 `_send(ws, msg)` 将结果发回发送者的单条 WebSocket。这个消息虽然被持久化到 `_admin` 频道的 chat log 中，但 **不会推送给其他订阅 `_admin` 频道的连接**（包括 AutoRouter）。

**对比两种发送方式：**

| 方式 | 函数 | 接收范围 | AutoRouter 能否收到 |
|:----|:-----|:---------|:------------------:|
| 单连接回复 | `_send(ws, msg)` | **仅发送者的 WS 连接** | ❌ |
| 频道广播 | `_broadcast_to_channel(ch, payload)` | **所有订阅该频道的连接** | ✅ |

**AutoRouter 的现状：**
- ✅ 代码版本：R90 🅰️ 监听补丁已存在（`_handle_message` 有 `is_admin` 白名单）
- ✅ WS 连接：以 `ws_5d1896c9f170` 正确连接到 `wss://wsim.datahome73.cloud/ws`
- ✅ WORK_PLAN：HTTP 200，`auto_chain: true`，链定义完整
- ❌ **日志：自 08:20 启动后没有任何消息被接收** — 因为 `_admin` 频道的消息没广播给它

### 1.3 为什么这个 bug 藏了 4 轮才被发现

| 轮次 | workspace 创建 | AutoRouter 触发 | 发现 bug |
|:----:|:-------------:|:---------------:|:--------:|
| R88 | ❌ 失败 | ❌ | 归因于 workspace 失败 |
| R89 | ❌ 失败 | ❌ | 归因于 workspace 失败 |
| R90 | ❌ 失败 | ❌ | 归因于 workspace 失败 + 缺少 _admin 监听 |
| R91 | ✅ **成功** | ❌ 仍不触发 | ✅ **终于暴露真正的根因** |

R91 🅰️ 修复了 workspace 创建上限后，workspace 创建成功、代码版本正确、连接正常，但 AutoRouter 仍不工作 —— 排除了所有其他可能后，终于定位到 `_send` vs `_broadcast_to_channel` 这个最底层的消息路由问题。

---

## 2. 方案设计

### 2.1 改动范围

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `server/handler.py` | `_cmd_pipeline_start()` return 前加 `_broadcast_to_channel()` | ~+14 行 |
| **合计** | **1 文件** | **~+14 行净增** |

**零修改：** `server/auto_router.py` ✅ · `server/workspace.py` ✅ · `config.py` ✅ · `tests/` ✅

### 2.2 改动方案

**位置：** `_cmd_pipeline_start()` 函数末尾，return 语句之前（当前 handler.py L2858 附近）

```python
# ── R92: 广播管线启动通知到 _admin（让 AutoRouter 等监听者收到） ──
try:
    broadcast_content = (
        f"🚀 **{round_name} 管线已启动**\\n"
        f"  Step: {start_step} → {target_role}\\n"
        f"  工作室: {ws_id}\\n"
        f"  {create_result}\\n"
    )
    # 如果 rollcall 变量存在且非空，追加到广播
    if rollcall_result and rollcall_result != "N/A":
        broadcast_content += f"  {rollcall_result}\\n"

    await _broadcast_to_channel(ADMIN_CHANNEL, {
        "type": "broadcast",
        "channel": ADMIN_CHANNEL,
        "from_name": "系统",
        "from_agent": SYSTEM_AGENT_ID,
        "content": broadcast_content.strip(),
        "ts": time.time(),
    })
    logger.info("R92: 已广播 %s 管线启动通知到 %s", round_name, ADMIN_CHANNEL)
except Exception as e:
    logger.error("R92: 广播 %s 管线启动通知失败: %s", round_name, e)
    # 不阻断主流程 — broadcast 失败不应阻止 pipeline_start 的正常返回
```

**关键设计决策：**

| 决策 | 选择 | 理由 |
|:-----|:-----|:------|
| 广播还是回复 | **额外广播**，不替换回复 | 发送者仍需收到原有回复（含完整细节） |
| broadcast 失败处理 | **try/except，不阻断** | 广播是辅助通知，不应影响主流程 |
| 改动位置 | `_cmd_pipeline_start` 末尾 | 此时所有逻辑已完成，修改风险最低 |
| 信号内容格式 | 与 handler 原有回复格式一致 | AutoRouter 的 `_extract_round` 依赖 `R{N}` 格式 |

### 2.3 AutoRouter 侧的兼容性

AutoRouter 现有的 `_handle_message` 对 `_admin` 频道的处理（R90 🅰️ 已实现）：

```python
# auto_router.py _handle_message()
is_admin = channel == "_admin"
# 信号1: 管线就绪
if "管线已启动" in content or "工作区已就绪" in content:
    round_name = self._extract_round(content)
    if round_name:
        await self._on_pipeline_ready(round_name)
    return
```

新增的广播内容包含 `🚀 **R92 管线已启动**` → `"管线已启动" in content` → `_extract_round` 提取 `R92` → `_on_pipeline_ready("R92")` → AutoRouter 开始接力。

**AutoRouter 侧零改动。**

### 2.4 全自动管线验证计划

部署后需要**第一次真正验证 AutoRouter 全自动管线**：

```python
# 验证流程:
# 1. ✅ 确认 auto-router.service 在运行
# 2. ✅ 确认 0 活跃工作室（old ones archived）
# 3. 发 !pipeline_start R92-test --work_plan_url <url>
# 4. 检查:
#    a. 工作室创建成功
#    b. AutoRouter _handle_message 日志出现
#    c. 小开 inbox 收到 Step 2 任务
#    d. 爱泰 inbox 收到 Step 3 任务（小开发 "✅ 完成" 后）
```

### 2.5 向后兼容

| 场景 | 影响 |
|:-----|:------|
| 不发 `!pipeline_start` | ✅ 零影响（新增代码只有 `_cmd_pipeline_start` 内执行） |
| broadcast 时连接异常 | ✅ try/except 不阻断 return |
| 旧 AutoRouter（无 _admin 监听） | ✅ 无影响（新增消息只是 _admin 频道多一条消息） |
| 手动 inbox 协调 | ✅ 完全不受影响 |
| 多人同时发 `!pipeline_start` | ✅ `_broadcast_to_channel` 是异步非阻塞的 |

---

## 3. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| 🅰️-1 | `_cmd_pipeline_start` return 前有 `_broadcast_to_channel` 调用 | 代码审查确认 |
| 🅰️-2 | 广播内容包含 round_name（如 `R92`）| AutoRouter 能 `_extract_round` |
| 🅰️-3 | 广播目标频道是 `ADMIN_CHANNEL` | `channel` 字段正确 |
| 🅰️-4 | broadcast 失败不阻断 return | try/except 包裹 |
| 🅰️-5 | 原有 `_send(ws, msg)` 回复不变 | 发送者仍收到完整回复 |
| 🅰️-6 | 无回归：其他 `!` 命令不受影响 | 回归测试 |
| 🅲-1 | **全自动管线验证：** AutoRouter 收到 _admin 广播后派活 Step 2 | `!pipeline_start` → 小开 inbox 有任务 |
| 🅲-2 | **全自动管线验证：** Step 2→3 自动接力 | 小开发 `✅ 完成` → 爱泰收到 |
| 🅲-3 | **全自动管线验证：** 6 Step 全线闭环 | PM 收 `🏁 全部完成` |

---

## 4. R92 管线 Step 定义

```
Step 1: PM — 需求文档 + WORK_PLAN → 推 dev
Step 2: Arch — 技术方案：_cmd_pipeline_start 广播方案 + auto_router 信号确认
Step 3: Dev — 编码：handler.py ~+14 行 broadcast（仅 1 文件）
Step 4: Review — 代码审查（重点：try/except 安全、不阻塞 return）
Step 5: QA — 测试验证（9 项验收）
Step 6: Ops — 合并 main + 启动全自动管线验证（史上第一次 🤞）
```

---

## 5. 风险与缓解

| 风险 | 等级 | 缓解 |
|:-----|:----:|:------|
| `_broadcast_to_channel` 参数错误导致异常 | 🟢 | try/except 包裹，不阻断 return |
| 广播消息被 AutoRouter 重复处理 | 🟢 | `_mark_seen(msg_id)` 去重已在 auto_router.py 实现 |
| 发送者收到两条相同消息（_send + _broadcast） | 🟢 | 发送者收到原有 `_send` 回复，`_broadcast` 也会到。但 AutoRouter 只处理 `_broadcast` 的。两条消息 ID 不同，`_mark_seen` 不会去重，但这是预期行为 |
| AutoRouter 收到 broadcast 后仍有其他 gap | 🟡 | 三级递进保底：自动→inbox→TG |
| **这是最后一次了吗？** | 🟡 | R88→R89→R90→R91→R92，每个迭代解决一层问题。R92 补完 broadcast 后，AutoRouter 全链路信号路径：`!pipeline_start` → `_admin broadcast` → AutoRouter `_handle_message` → `_on_pipeline_ready` → `_fetch_topology` → `_dispatch_step`。理论上无更多 gap。 |
