# R87 工作计划 — `_inbox:server` 中继架构 🚉

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R87/R87-product-requirements.md v1.2
> **日期：** 2026-07-09

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小（~70 行净增），严禁 scope creep**

- ✅ 改入：server 端 `_handle_server_relay()` 中继函数 + 入口集成 + 安全守卫
- ✅ 改入：config 层 `SERVER_INBOX_CHANNEL` 常量 + `PM_AGENT_ID` + 确认模板
- ✅ 改入：bot 端回复目标从 `_inbox:<PM_id>` 改为 `_inbox:server`
- ❌ 不改：PM 派活方式（仍直接发 `_inbox:<bot_id>`，保持不变）
- ❌ 不改：客户端库 `ws_client.py` 协议（如需 `send_to_server()` 辅助方法，可选但不必须）
- ❌ 不改：Web 端、Agent Card、管线状态机、workspace 逻辑
- ❌ 不改：现有 `inbox-message-protocol.md`（部署后统一更新）

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署+文档更新 | operations | architect | |

### 0.3 通道使用规则（本轮核心）

| 通道 | 谁发 | 谁收 | 用途 |
|:-----|:-----|:-----|:------|
| `_inbox:<bot_id>` | PM、Server | **Bot** | 任务派发 + 自动确认 |
| `_inbox:<PM_id>` | Server | **PM** | 进度/结果转发通知 |
| `_inbox:server` | **仅限 Bot** | **Server 内部** | Bot 回复中继，PM/Server 均不走此通道 |

---

## 1. 管线总览

### 核心通信流

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ────────────────────────────────→ _inbox:<bot_id> ──────────→│
│   PM直接发bot收件箱，不走server        │                              │
│                                  │                                  │
│                                  │←── ② ACK ✅ R{N} 收到！─────────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK（进度通知）──────────┤                                  │
│                                  │                                  │
│                                  │         [bot 干活中...]         │
│                                  │                                  │
│                                  │←── ④ ✅ 完成，已推 dev: xxx ───┤
│                                  │     (_inbox:server) ← 唯一触发点 │
│←── ⑤ 转发 完成 ──────────────────┤                                  │
│         (通知PM)                  │── ⑥ 自动确认 ──────────────────→│
│                                  │    (回复bot，_inbox:<bot_id>)     │
│                                  │ ⑤+⑥ 同时触发，无先后顺序        │
```

### 改动范围

仅 `server/handler.py` + `server/__main__.py` + `server/config.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:-----|:-----|:----:|
| 1 | **核心** | 新增 `_handle_server_relay()` 中继函数 + `is_server_inbox()` 判断 | `handler.py` 模块级 | ~40 行 |
| 2 | **核心** | 入口集成：`handler()` 中在 `handle_broadcast` 前增加 `_inbox:server` 拦截 | `handler.py` L6165 附近 | ~5 行 |
| 3 | **核心** | 入口集成：`ws_handler()` 中同样增加拦截 | `__main__.py` L104 附近 | ~5 行 |
| 4 | **安全** | 中继函数内 PM 误发 `_inbox:server` 的拒绝守卫 | `handler.py` 中继函数内 | ~10 行 |
| 5 | **配置** | 新增 `SERVER_INBOX_CHANNEL` + `PM_AGENT_ID` + `completion_ack_template` | `config.py` | ~5 行 |
| 6 | **文档** | 部署后更新 `inbox-message-protocol.md` §8（不在此次编码范围） | 部署后执行 | — |

**总估算：** ~70 行净增，3 文件改动

### 核心函数签名

```python
async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    """
    处理发往 _inbox:server 的消息（仅接受 bot）
    返回 True 表示已由中继处理（不继续路由）
    返回 False 表示不是中继消息（继续现有路由）
    
    规则：
    - content.startswith("ACK ✅") → 转发 PM（进度通知）
    - content.startswith("✅ 完成") → 转发 PM + 自动确认 bot（同时触发）
    - agent_id == PM_AGENT_ID → 拒绝（PM 不应发 _inbox:server）
    - 其他 → 沉默
    """
```

### 安全设计要点

| # | 场景 | 防护 |
|:-:|:-----|:------|
| ❶ | PM 误发消息到 `_inbox:server` | 判断 `agent_id == PM_AGENT_ID`，返回 error + 拒绝 |
| ❷ | Step ⑤+⑥ 混淆先后顺序 | 两个 `await _send_to_agent()` 在同一个函数内顺序执行，语义上同时触发 |
| ❸ | Step ⑥ 发 `_inbox:<bot_id>` 而非 `_inbox:server` | 伪代码中明确 `channel="_inbox:<sender_id>"` |
| ❹ | 一条消息同时匹配 ACK 和完成（如 `ACK ✅ 已完成`） | 先匹配 ACK，匹配后 `return True`，不继续匹配 |

---

## 2. 管线步骤

### Step 2：技术方案（Arch）

**主角：** architect（小开） | **备用：** developer（爱泰）

**阅读材料：**
- 📄 需求文档：`docs/R87/R87-product-requirements.md`
- 🔗 涉及代码：`server/handler.py`（新增 `_handle_server_relay` + 入口集成）、`server/__main__.py`（ws_handler 入口集成）、`server/config.py`（新增常量）
- 📖 当前 inbox 协议：`docs/inbox-message-protocol.md` §8（将被替换的旧模型）

**任务：**
1. 确认 `_handle_server_relay()` 的最佳代码位置（handler.py 模块级函数 vs handler 类的独立方法）
2. 确认 PM_AGENT_ID 的获取方式（config 启动时读取 vs handler 运行时查找）
3. 确认 `_send_to_agent()` 函数是否已具备 `target_id` + `content` + `from_name` 签名（不需要额外参数）
4. 输出技术方案文档 `docs/R87/R87-tech-plan.md`，含每个改动的精确行号 + 代码对比

**完成条件：** 技术方案已推 dev，含所有方向的实现路径

---

### Step 3：编码实现（Dev）

**主角：** developer（爱泰） | **备用：** architect（小开）

**阅读材料：**
- 📄 需求：`docs/R87/R87-product-requirements.md`
- 🏗️ 技术方案：`docs/R87/R87-tech-plan.md`
- 🔗 现有代码：`server/handler.py`、`server/__main__.py`、`server/config.py`

**任务：**
1. **config.py** — 新增 `SERVER_INBOX_CHANNEL` 常量 + `PM_AGENT_ID` 配置项 + `completion_ack_template`
2. **handler.py** — 实现 `is_server_inbox()` 判断函数
3. **handler.py** — 实现 `_handle_server_relay()` 中继函数（含 3 条转发规则 + PM 安全守卫）
4. **handler.py** — `handler()` 入口集成（`handle_broadcast` 前拦截）
5. **__main__.py** — `ws_handler()` 入口集成（同上）

**编码约束：**
- 中继函数必须处理 `_inbox:server` → `_inbox:<PM_id>` 和 `_inbox:<bot_id>` 两种转发方向
- `_handle_server_relay()` 返回 `bool` 标识已处理，调用处通过返回值决定是否继续路由
- PM 安全守卫在函数入口处，拒绝后**不阻断连接**（仅拒绝消息+返回 error）
- 不要修改 `handle_broadcast()` 现有逻辑
- 不要引入 `_inbox:server` 以外的特殊通道

**完成条件：** 3 文件改动完毕，git push dev，告知 SHA

---

### Step 4：代码审查（Review）

**主角：** reviewer（小周） | **备用：** qa（泰虾）

**审查重点：**
1. ✅ `_handle_server_relay()` 是否正确处理 3 种输入（ACK ✅ / ✅ 完成 / 其他）
2. ✅ Step ⑤+⑥ 是否同时触发（语义上，非硬性同时）
3. ✅ Step ⑥ 的确认消息是否发到 `_inbox:<bot_id>`（而非 `_inbox:server`）
4. ✅ PM 安全守卫是否正确：`agent_id == PM_AGENT_ID` 时拒绝，`return True`
5. ✅ 入口集成位置是否正确（`handle_broadcast` 之前，key 验证之后）
6. ✅ 零 scope creep（不引入不在范围的改动）
7. ✅ 旧 bot 沿用 `_inbox:<PM_id>` 回复不受影响（旧路径不经过 `_handle_server_relay`）

**完成条件：** 审查报告已推 dev，结论 🟢 通过 / 🟡 条件通过 / 🔴 退回

---

### Step 5：测试验证（QA）

**主角：** qa（泰虾） | **备用：** reviewer（小周）

**验收清单（从需求文档复制）：**

**核心功能：**

| # | 检查项 | 测试方法 |
|:-:|:-------|:---------|
| ✅-1 | Bot 发 `ACK ✅` 到 `_inbox:server`，PM 收到转发 | bot 发 ACK → 检查 PM 收件箱 |
| ✅-2 | Bot 发 `✅ 完成` 到 `_inbox:server`，PM 收到转发 | bot 发完成 → 检查 PM 收件箱 |
| ✅-3 | Bot 发 `✅ 完成` 后，server 自动确认到 bot inbox | 检查 bot 收件箱 |
| ✅-4 | Bot 发非关键内容（如 `"正在思考..."`）→ 沉默 | bot 发杂音 → PM 收件箱无此消息 |
| ✅-5 | 非 `_inbox:server` 的消息不受影响 | 普通 inbox 消息正常路由 |

**路由安全：**

| # | 检查项 | 测试方法 |
|:-:|:-------|:---------|
| ✅-6 | PM 误发消息到 `_inbox:server` | PM 发 `_inbox:server` → 看 error 响应 |
| ✅-7 | Step 4 确认发到 `_inbox:<bot_id>`（不走 `_inbox:server`） | 日志 grep channel 确认 |
| ✅-8 | `ACK✅`（无空格）→ 不触发转发 | 发送测试 |
| ✅-9 | `✅完成`（无空格）→ 不触发完成转发 | 发送测试 |
| ✅-10 | 多个 bot 同时发消息到 `_inbox:server` | 同时发 10 条，独立转发 |
| ✅-11 | 未注册 bot 发 `_inbox:server` | 现有 key 验证拦截 |
| ✅-12 | Step 4 确认后 bot 再回复 | bot 回确认消息，按前缀走中继 |

**文档更新（部署后验证）：**

| # | 检查项 |
|:-:|:-------|
| ✅-13 | inbox-message-protocol.md §8 已更新（通信图、通道职责表、前缀规则、Bot Checklist） |

**完成条件：** 测试报告已推 dev，13/13 验收通过 ✅

---

### Step 6：合并部署归档 + 文档更新（Operations）

**主角：** operations（小爱） | **备用：** architect（小开）

**任务：**
1. `git checkout main && git merge dev && git push origin main`
2. `docker build -t ws-bridge:r87 .`
3. `docker stop ws-bridge-prod && docker rm ws-bridge-prod`
4. `docker run -d --name ws-bridge-prod ... ws-bridge:r87`
5. `!pipeline_status R87` 确认容器健康
6. `!close_workspace ws:xxx` 关闭工作室（如适用）
7. `docs/TODO.md` 更新版本号

**部署后文档更新（⚠️ 关键）：**
8. **更新 `docs/inbox-message-protocol.md` §8：**
   - 替换通信全景 ASCII 图为 `_inbox:server` 中继模型
   - 新增通道职责表（§2.1 通道职责严格分离）
   - Step 1 派活：PM 直接发 `_inbox:<bot_id>`（不走 server relay）
   - Step 2 ACK 回复目标：改为 `_inbox:server`
   - Step 3 完成回复目标：改为 `_inbox:server`
   - Step 6 自动确认：Server 发到 `_inbox:<bot_id>`（bot 不回复）
   - 新增前缀规则说明（ACK ✅ / ✅ 完成 / 其他 → 沉默）
   - 新增 PM 安全守卫说明（PM 误发 `_inbox:server` 被拒）
   - 更新 Bot Checklist（回复地址检查项）
   - 移除 SENDER_INBOX 字段概念

**⚠️ 注意：** git push ≠ 已部署。必须重建镜像再 run 新容器，光 restart 不行。文档更新必须随本次部署一起完成——`inbox-message-protocol.md` 有滞后就会导致新旧协议混乱。

---

## 3. 验收清单（从需求文档复制）

### 🎯 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Bot 发 `ACK ✅` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"📬 Bot名 已接活: ACK ✅ ..."` | bot 发 ACK → 检查 PM 收件箱 |
| ✅-2 | Bot 发 `✅ 完成` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"✅ Bot名 任务完成: ✅ 完成..."` | bot 发完成 → 检查 PM 收件箱 |
| ✅-3 | Bot 发 `✅ 完成` 后，server 自动回复确认到 bot inbox | bot 收到 `"✅ 确认，已收到你的完成通知"`（发到 `_inbox:<bot_id>`） | 检查 bot 收件箱 |
| ✅-4 | Bot 发非关键内容（如 `"正在思考..."`）→ 沉默 | PM 不收到此消息，bot 也不收回复 | bot 发杂音 → 检查 PM 收件箱无此消息 |
| ✅-5 | 非 `_inbox:server` 的消息不受影响 | 普通 inbox 消息正常路由（向后兼容） | 正常发消息 → 检查现有路由不变 |

### 🎯 路由安全

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-6 | PM 误发消息到 `_inbox:server` | Server 拒绝，返回 error `"_inbox:server 仅接受 bot 消息"` | PM 发 `_inbox:server` → 看响应 |
| ✅-7 | Step 4 确认发到 `_inbox:<bot_id>`（不走 `_inbox:server`） | 检查 server 发确认时 channel 为 `_inbox:<bot_id>` | 日志 grep channel 确认 |
| ✅-8 | `ACK✅`（无空格）→ 不触发转发 | PM 不收到 ACK 通知 | 发送测试 |
| ✅-9 | `✅完成`（无空格）→ 不触发完成转发 | PM 不收到完成通知 | 发送测试 |
| ✅-10 | 多个 bot 同时发消息到 `_inbox:server` | 各自独立转发，互不影响 | 同时发 10 条 |
| ✅-11 | Bot 未注册就发到 `_inbox:server` | 按现有 key 验证逻辑拒绝（不会进入中继） | 未 auth 的连接发消息 |
| ✅-12 | Step 4 确认后 bot 再回复 → 走正常中继路径 | bot 回复到 `_inbox:server`，按前缀匹配处理（大概率沉默） | bot 回 Step 4 确认的消息 |

### 🎯 文档更新

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-13 | inbox-message-protocol.md §8 更新 | 全流程改为 `_inbox:server` 中继模型，附通道职责表、前缀规则、Bot Checklist 更新 |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R87 `_inbox:server` 中继架构 |

---

## 5. 脱敏检查清单

- [ ] docs/R87/*.md 零内部名残留
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
