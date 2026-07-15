# R119 自动派活全流程跑通 — 技术方案

> **轮次：** R119
> **类型：** 生产验证轮（零代码改动基线，断点治本）
> **架构师：** 小开
> **基线：** ws-bridge:r118（含 R117 `_resolve_card_key_to_ws_id()` 三策略 fallback）
> **参考：** [R119 需求文档](./R119-product-requirements.md)，[WORK_PLAN](./WORK_PLAN.md)

---

## 一、验证范围

### 1.1 验证目标

在生产环境完整跑通以下链路，**不跳过任何一步**：

```
##start##R119
  → _handle_hash_start() 创建 PipelineContext
  → _auto_dispatch(ctx, 1) 派活 Step 1 给小谷
  → 小谷回复 "已完成 ✅ R119 Step 1"
  → _try_advance_pipeline() 推进至 Step 2
  → _auto_dispatch(ctx, 2) 派活 Step 2 给小开（本轮所在之处）
  → 小开回复 "已完成 ✅ R119 Step 2"
  → _try_advance_pipeline() 推进至 Step 3
  → _auto_dispatch(ctx, 3) 派活 Step 3 给爱泰
  → ... 直至 Step 6 → COMPLETED
```

### 1.2 验证对象（代码路径）

| 代码路径 | 文件 | 验证内容 |
|:---------|:-----|:---------|
| `_handle_hash_start()` | `main.py ~L2907` | `##start` 创建管线、Steps 赋值、name_to_ws 桥接 |
| `_auto_dispatch()` | `main.py ~L2515` | card key → WS ID fallback（R117）、派活模板渲染、消息落库 |
| `_send_to_agent()` | `main.py ~L2348` | 定向发送到目标 bot 的 WS 连接 |
| `_try_advance_pipeline()` | `main.py ~L2410` | Step 完成消息解析、推进逻辑、auto_dispatch 调用 |
| `_handle_server_relay()` | `main.py ~L2690` | `_inbox:server` 消息中继转发到 PM |

### 1.3 不纳入验证

| 内容 | 理由 |
|:-----|:------|
| `PipelineAutoStarter`（PAS） | 已关闭（`PAS_ENABLED=0`），容器缺 git |
| 离线重试机制 | 已验证过，本轮聚焦在线全链路 |
| PM 通知格式 | R115/R116 已定稿，本轮只验证路由可到达 |

---

## 二、环境前置条件

### 2.1 服务器配置检查清单

| # | 检查项 | 预期 | 验证方法 |
|:-:|:-------|:-----|:---------|
| ENV-1 | `WS_PM_AGENT_ID` | `ws_f26e585f6479` | `docker exec ws-bridge env \| grep WS_PM` |
| ENV-2 | `PAS_ENABLED` | `0` | `docker exec ws-bridge env \| grep PAS` |
| ENV-3 | 容器镜像 | `ws-bridge:r119` | `docker inspect ws-bridge \| jq '.[0].Config.Image'` |
| ENV-4 | `AUTO_DISPATCH_ENABLED` | `True`（默认） | 日志 `[R107] auto_dispatch` 出现 |
| ENV-5 | 6 个 bot 已连接 | 所有 bot 在线 | `/api/agents/status` 检查 |
| ENV-6 | `agent_cards.json` | role 映射对齐 pipeline 短名 | SSH 检查卡文件内容 |

### 2.2 Bot 连接状态预期

| Bot | agent_id | 角色 | 在线预期 |
|:----|:---------|:-----|:---------|
| 小谷 | `ws_f26e585f6479` | PM | ✅ 必须在线（发 `##start`） |
| 小开 | `ws_3f7cdd736c1c` | Arch | ✅ 必须在线 |
| 爱泰 | 待查 | Dev | ✅ 必须在线 |
| 小周 | 待查 | Review | ✅ 必须在线 |
| 泰虾 | 待查 | QA | ✅ 必须在线 |
| 小爱 | 待查 | Ops | ✅ 必须在线（部署操作） |

---

## 三、逐 Step 验证流程

### 3.1 Step 1 — PM 启动管线

**操作：**
```
小谷发送: ##start##R119
```

**预期自动行为时序：**
```
t=0s:  _handle_hash_start() 创建 R119 管线
        ├─ role_map → agents[0] for Step 1 = "product-manager-bot" (card key)
        ├─ name_to_ws bridge → "ws_f26e585f6479" (小谷)
        ├─ 每个 step 的 agent_id 均应为 ws_xxx 格式
        ├─ PipelineContext 落盘 + 广播 ✅ 已启动
        └─ asyncio.ensure_future(_auto_dispatch(ctx, 1))

t=1s:  _auto_dispatch() Step 1
        ├─ next_step_info["agent_id"] → 应为 ws_xxx ✅
        ├─ _render_template() → 派活消息
        └─ _send_to_agent(ws_f26e585f6479, payload)
             └─ 小谷的 _inbox 收到 Step 1 任务消息
```

**3 项检查：**
| # | 检查项 | 方法 |
|:-:|:-------|:------|
| ① ✅ | 小谷收到 `✅ 已启动` 系统回复 | 小谷 inbox 查看 |
| ② 🚀 | 小开自动收到 Step 2 派活消息 | 小开 inbox 查看 `[R119] Step 2` |
| ③ 📬 | 小谷收到 Step 2 派活通知 | 小谷 inbox 查看下步派活通知 |

> **注意：** 如果 Step 2 自动派活到小开但小开没收到 → **此处暂停，记录日志，源码修复。** 这是本轮最重要的验证点（R117 修复是否生效）。

### 3.2 Step 2 — 小开技术方案（当前步骤）

**操作：**
```
小开:
  1. 编写技术方案 → 推 git dev
  2. 发送 "已完成 ✅ R119 Step 2" 到 _inbox:server
```

**预期自动行为时序：**
```
t=0s:  _handle_server_relay() 规则 2 收到 R119 Step 2 完成
        ├─ 转发 PM + 自动确认 bot
        └─ _try_advance_pipeline(R119, content)

t=1s:  _try_advance_pipeline()
        ├─ 正则匹配: round=R119, step=2
        ├─ _extract_artifact_kv() → artifacts
        ├─ mgr.advance_step() → current_step=3
        └─ 日志 "[R117] R119 Step 2 已完成，尝试自动派活 Step 3"

t=2s:  _auto_dispatch(ctx, 3)
        ├─ target_agent_id = step3_info["agent_id"]
        ├─ 非 ws_ 前缀 → _resolve_card_key_to_ws_id(card_key)
        │   ├─ 策略 1: display_name → api_keys ✅
        │   └─ target_agent_id → ws_xxx of 爱泰
        ├─ _render_template() → Step 3 派活消息
        └─ _send_to_agent(爱泰的 ws_id, payload)
             └─ 爱泰的 _inbox 收到 Step 3 任务
```

**3 项检查：**
| # | 检查项 | 方法 |
|:-:|:-------|:------|
| ① ✅ | 小开收到 `✅ 确认` 系统回复 | 小开 inbox |
| ② 🚀 | 爱泰自动收到 Step 3 派活消息 | 爱泰 inbox 查看 |
| ③ 📬 | 小谷收到 Step 3 派活通知 | 小谷 inbox 查看 |

### 3.3 Step 3~6 同理

每个 Step 完成后的检查点一致（① 系统确认 ② 下步自动派活 ③ PM 通知），不再重复列出。

---

## 四、断点处理协议

### 4.1 原则

**不手动绕行，不临时 workaround。** 碰到任何一个断点（① ② ③ 任何一项失败）→ **暂停推进** → **现场记录** → **源码修复** → **重试同一环节**。

### 4.2 断点记录模板

```
--- 断点记录 ---
时间: 2026-07-15T14:30:00+07
位置: Step 2 → ③ 📬 PM 通知失败
现象: 小谷未收到 Step 3 派活通知
日志: [R117] _send_to_agent(...): 无目标连接 (sent=0)
根因: pm_agent_id 在通知路由中用了 card key "pm-bot" 而非 ws_f26e585f6479
修复: main.py Lxxxx 增加 resolve_card_key_to_ws_id() 调用
提交: a1b2c3d4
--- 断点已修复，继续验证 ---
```

### 4.3 断点分类

| 类型 | 严重度 | 处理方式 |
|:-----|:-------|:---------|
| ① 系统确认失败 | 🔴 阻塞 | 修复 _handle_server_relay 或 _send_to_agent |
| ② 自动派活失败 | 🔴 阻塞 | 修复 _auto_dispatch 或 _resolve_card_key_to_ws_id |
| ③ PM 通知失败 | 🟡 非阻塞 | 继续推进，记录后修复通知路由 |

---

## 五、观察记录模板

### 5.1 每步记录

```
--- Step N 验证记录 ---
时间: YYYY-MM-DD HH:MM
操作者: xxx
操作: 具体做了什么
 ① ✅ 系统确认: [通过/失败]
 ② 🚀 下步派活: [通过/失败 → 发送给谁]
 ③ 📬 PM 通知: [通过/失败]
断点?: [无/有 → 参考断点记录#N]
耗时: N 分钟
备注: 任何观察
```

### 5.2 最终输出

验证完成后由 QA（泰虾）汇总为 `docs/R119/R119-verification-report.md`，包含：
- 6 步各自耗时
- 所有断点记录
- 修复 commit SHA 列表
- 最终状态（全部通过 / 部分失败）

---

## 六、验证终止条件

| 条件 | 动作 |
|:-----|:------|
| 6 步全部验证通过，3×6=18 项检查点 ALL GREEN | ✅ R119 成功，转入 Step 6 合并部署 |
| 发现无法短期内修复的严重 Bug | 🔄 R119 暂停，开 R120 修复轮 |
| 某 bot 持续离线（30min 以上） | ⏸️ 等待 bot 上线后继续 |
| 服务端崩溃 | 🔴 小爱介入恢复，记录崩溃现场 |

---

> **拟定者：** 小开
> **日期：** 2026-07-15
> **状态：** 定稿

### 附：技术方案摘要

R119 不涉及任何代码新增或数据结构变更。整个验证轮的核心只有：

```
确认 3 条路径全部工作:
  ① _send_to_agent(ws_id) → bot._inbox 收到 ✅
  ② _try_advance_pipeline(round, step) → current_step+1 → _auto_dispatch ✅
  ③ _auto_dispatch(...) → _resolve_card_key_to_ws_id() → ws_id → _send_to_agent ✅
```
