# R41 技术验证方案

> **版本：** v1.0
> **状态：** ✅ 待评审
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-27
> **需求文档：** [R41-product-requirements.md](R41-product-requirements.md)
> **工作计划：** [WORK_PLAN.md](WORK_PLAN.md)

---

## 0. 方案概述

| 区块 | 内容 | 验证项 | 条件性修复 |
|:-----|:-----|:------:|:----------:|
| **Part A** | Bug 验证 + 回归 | V-A1~V-D5 | FIX-A1~FIX-D2 |
| **Part B** | 条件性修复方案 | — | 6 个可选方案 |

### 执行路线图

```
V-A1~V-A3 (Web认证环境)  → 如 ❌ → FIX-A1/A2
V-B1~V-B4 (消息重复)     → 如 ❌ → FIX-B1/B2
V-C1~V-C3 (进度Tab空白)  → 如 ❌ → FIX-C1/C2
V-D1~V-D5 (点名流程拆解)  → 如 ❌ → FIX-D1/D2
                     ↓
            全部 🟢 → 跳过 Step 4/5，直接 🦐 测试工程师
```

---

# Part A — 验证方案

---

## 方向 A — Web 认证环境区分

### V-A1 — 开发环境：绑定码 + OAuth 双入口显示

**目标：** 确认开发环境中登录页同时展示绑定码区域和 GitHub 登录按钮

**前置条件：**
- 开发 VPS 部署运行中（`ws-im-dev.datahome73.com`）
- `GITHUB_OAUTH_CLIENT_ID` 环境变量已配置

**验证步骤：**
1. 浏览器打开 `https://ws-im-dev.datahome73.com/`
2. 观察登录页元素：
   - 🔑 绑定码区域（`#bindCode` 显示 code）
   - 🐙 GitHub 登录按钮（`#githubLoginBtn`）
3. 点击 GitHub 按钮，确认跳转到 GitHub OAuth 授权页

**期望结果：**
- 绑定码框自动显示 WEB-XXX 代码 ✅
- GitHub 登录按钮可见并可点击 ✅
- 两条路径均可完成登录

**验收标准：** A-1 满足

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/templates.py:31-45` | BIND_TEMPLATE — 硬编码 HTML，无条件渲染 | ⏳ 待验证 |
| `server/web_viewer.py:186-190` | `handle_api_bind()` — 始终生成绑定码 | ⏳ 待验证 |
| `server/web_viewer.py:399-417` | `handle_github_login()` — 501 仅当 CLIENT_ID 为空 | ⏳ 待验证 |
| `server/config.py:5-35` | 无 `ENV`/`WS_ENV` 环境变量读取 | ⏳ 待验证 |
| `server/web_viewer.py:526-545` | `setup_routes()` — 所有路由无条件注册 | ⏳ 待验证 |

---

### V-A2 — 生产环境：仅 OAuth，无绑定码

**目标：** 确认生产环境中登录页隐藏绑定码区域，仅显示 GitHub 登录

**前置条件：**
- 生产容器运行中（`ws-bridge.datahome73.com`）
- `GITHUB_OAUTH_CLIENT_ID` 配置

**验证步骤：**
1. 浏览器打开 `https://ws-bridge.datahome73.com/`
2. 观察登录页：
   - 不应出现绑定码 `#bindCode` 区域
   - 不应出现 `#githubLoginSection` 后面的绑定码说明
   - GitHub 登录按钮应存在且可用
3. 直接请求 `GET /api/bind`，期望返回 404 或禁用提示
4. 直接请求 `GET /api/check?code=WEB-XXXXX`，期望返回 404 或禁用提示

**期望结果：**
- 登录页仅展示 GitHub 登录按钮 ✅
- `/api/bind` 和 `/api/check` 返回 404 或明确的禁用提示 ✅
- 用户无法通过绑定码路径进入聊天

**验收标准：** A-2, A-3 满足

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/templates.py:31-45` | 静态 HTML — 无环境判断条件 | ❌ 需要改为动态渲染 |
| `server/web_viewer.py:529-530` | `/api/bind`、`/api/check` 路由始终注册 | ⏳ 待验证 |
| `server/config.py:5` | 无 `ENV`/`IS_PROD` 配置 | ❌ 需要新增 |

---

### V-A3 — 环境切换通过配置完成

**目标：** 确认环境切换仅需环境变量，不修改代码

**验证步骤：**
1. 检查 `config.py`：添加 `WS_ENV=production` 后，登录页行为变化
2. 检查 `templates.py`：是否基于配置动态渲染
3. 检查 `web_viewer.py`：`/api/bind` 路由是否条件性注册

**期望结果：**
- 仅需设置 `WS_ENV=production`（或在启动命令加参数），无需改代码行 ✅
- dev 默认行为不变（后向兼容）✅

**验收标准：** A-4 满足

---

## 方向 B — 活跃工作室消息重复（回归修复）

### V-B1 — 双写根因验证：save_message + write_chat_log

**目标：** 确认每条消息经由 handle_broadcast 产生两次 DB 写入

**前置条件：**
- 开发环境运行中
- 测试 agent 在线，加入一个活跃工作室

**验证步骤：**
1. 发送一条消息到工作室频道
2. 检查 SQLite `messages` 表：`SELECT * FROM messages WHERE content='<test content>' ORDER BY ts`
3. 验证是否有两条记录（不同 `msg_id`、相近 `ts`）
4. 检查 `save_message()` 调用路径：
   - `handler.py:~1020` — 直接调用
   - `web_viewer.py:63` — 通过 `write_chat_log()` 间接调用

**期望结果：**
- 确认两条完全相同的记录（仅 `msg_id` 和 `ts` 微差）✅
- 确认两条记录分别来自 `save_message` 的直接调用和通过 `write_chat_log` 的间接调用 ✅

**验收标准：** B-1, B-2 根因确认

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:1020-1031` | 工作室路径：`ms.save_message(... channel=channel)` | ✅ 已确认 |
| `server/handler.py:1094` | 工作室路径：`write_chat_log(... channel=channel)` | ✅ 已确认 |
| `server/handler.py:1215-1225` | 大厅路径：`ms.save_message(...)` 默认 lobby | ✅ 已确认 |
| `server/handler.py:1183/1317` | 大厅路径：`write_chat_log(...)` 默认 lobby | ✅ 已确认 |
| `server/web_viewer.py:35-91` | `write_chat_log()` — 内部调 `ms.save_message()` + 写日志 + WS 推送 | ✅ 已确认 |
| `server/message_store.py:64-86` | `save_message()` — `INSERT OR IGNORE` 使用 UUID 主键 → 永不命中 | ❌ 无效去重 |
| `server/handler.py:1501-1508` | `_is_duplicate()` — 同 agent + 同 content + 30 秒 | ⏳ 待验证 |

---

### V-B2 — 前端去重：_seenMsgHashes 哈希表验证

**目标：** 确认前端去重哈希表的有效性，识别其失效场景

**前置条件：**
- 浏览器打开 Web UI 聊天页
- 加入活跃工作室

**验证步骤：**
1. 发送多条消息到工作室
2. 观察前端渲染：每条消息是否只显示一次
3. 快速切换 Tab（active ↔ lobby ↔ progress）多次
4. 等待 `_seenMsgHashes` 累积超过 500 条后，观察是否复现重复
5. 检查 WebSocket 消息流：是否同时收到 `type: "broadcast"` 和 `type: "chat_message"` 两类消息

**期望结果：**
- 正常情况下无重复 ✅
- Tab 切换后无重复 ✅
- 去重哈希超过 500 后也可能出现重复（设计局限）✅

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/templates.py:340-347` | `loadMessages()` — `chKey = channel\|ts\|sender\|content[:80]` | ⏳ 待验证 |
| `server/templates.py:358-367` | `appendMessage()` — 同上，哈希溢出删除前 200 | ⏳ 待验证 |
| `server/templates.py:182` | `const _seenMsgHashes = {}` — 全局单例 | ⏳ 待验证 |
| `server/templates.py:630-633` | 30 秒轮询 — 调用 `renderProgressTab()` | ⏳ 待验证 |

---

### V-B3 — 前端双流重复验证

**目标：** 确认 Web Viewer 同时通过 agent WS 和 web WS 收到同一条消息

**前置条件：**
- 浏览器 Web UI 打开并连接到工作室
- 浏览器 devtools 控制台打开

**验证步骤：**
1. 发送一条消息到工作室
2. 在浏览器控制台监听 WebSocket 消息事件
3. 检查是否收到两条内容相同的消息：
   - 一条 `type: "broadcast"`（来自 agent 广播）
   - 一条 `type: "chat_message"`（来自 `write_chat_log` WS 推送）
4. 对比两消息的 `ts` 字段：是否相差 1ms+

**期望结果：**
- 同一工作室消息以两条不同 WS 消息到达前端 ✅
- `_seenMsgHashes` 可能因 ts 微差无法去重 ✅
- 确认此为双流架构的系统性重复根因 ✅

**验收标准：** B-3 根因确认

---

### V-B4 — 长时间使用去重稳定性

**目标：** 验证长时间使用下去重哈希不会被 500 条溢出突破

**前置条件：**
- 持续使用工作室 10 分钟+（可自动脚本模拟）

**验证步骤：**
1. 使用测试脚本持续发送消息（约 50 条/分钟）
2. 监控前端渲染：每 60 秒截图记录消息列表
3. 检查是否在 `_seenMsgHashes` 溢出（超过 500）后出现重复
4. 持续 10 分钟以上

**期望结果：**
- 如果在溢出窗口期间有两条流同时推送，消息会重复 ✅
- `_seenMsgHashes` 溢出频率 ≈ 500/rate，消息密集时约每 30 秒溢出一次

**验收标准：** B-4 根因确认

---

## 方向 C — 进度 Tab 空白

### V-C1 — _broadcast_task_notify 是否被调用

**目标：** 确认 `_cmd_task_create` 和 `_cmd_task_update` 是否调用了 `_broadcast_task_notify`

**前置条件：**
- 开发环境运行中
- 有一个活跃工作室

**验证步骤：**
1. 在工作室发送 `!task_create --context R41 --name "编写代码" --role dev-bot`
2. 观察服务器日志：是否出现 `"task_notify"` 关键字
3. 检查代码：`_cmd_task_create` 末尾是否有 `await _broadcast_task_notify(task, "→ WORKING")` 调用
4. 发送 `!task_update <task_id> --state WORKING`
5. 检查日志：是否打印 `"task_notify"`

**期望结果：**
- 日志不出现 `"task_notify"` ✅（确认从未被调用）
- 代码中 `_broadcast_task_notify` 定义于 handler.py:795，零调用站点 ✅

**验收标准：** C-1 根因确认

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:615-632` | `_cmd_task_create()` — 创建 task → 返回文本 | ❌ 未调 notify |
| `server/handler.py:635-678` | `_cmd_task_update()` — 更新 state → 返回文本 | ❌ 未调 notify |
| `server/handler.py:795-844` | `_broadcast_task_notify()` — 定义但零调用站点 | 🟡 死亡代码 |
| `server/handler.py:774-780` | `_ADMIN_COMMANDS` 注册 task_create/task_update | ✅ 已注册 |
| `server/__main__.py:614-626` | 仅处理 agent 主动发送的 MSG_TASK_NOTIFY WS 消息 | ⏳ 待验证 |

---

### V-C2 — MSG_TASK_NOTIFY 到 _admin 通道写入路径

**目标：** 确认 `_broadcast_task_notify` 是否将 📊 数据写入 `_admin` 聊天日志

**验证步骤：**
1. 手动触发 `_broadcast_task_notify`（通过 mock 或直接调测试）
2. 检查 `_admin` 通道的聊天日志：`cat data/logs/chat_<date>.log | grep "📊"`
3. 检查 SQLite：`SELECT * FROM messages WHERE channel='_admin' AND content LIKE '📊%'`
4. 检查前端：调用 `GET /api/chat?channel=_admin` 是否返回 📊 消息

**期望结果：**
- `_admin` 日志中没有 📊 开头的消息 ✅
- `/api/chat` 不返回任何 📊 数据 ✅
- 确认 `_broadcast_task_notify` 不调用 `write_chat_log()` ✅

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:831-842` | `_broadcast_task_notify` — 仅 WS 推送原始 JSON | ❌ 未写 chat log |
| `server/web_viewer.py:35-91` | `write_chat_log()` — 写日志 + DB + WS 推送 | 仅被 handler 广播调 |
| `server/templates.py:454-520` | `renderProgressTab()` — `GET /api/chat?channel=_admin` 过滤 📊 | ❌ 无数据 |
| `server/__main__.py:622-624` | 唯一写 📊 到 `_admin` 的路径（agent WS 消息触发） | ⏳ 待验证 |

---

### V-C3 — 前端 renderProgressTab 数据来源验证

**目标：** 确认前端进度 Tab 的数据来源和渲染逻辑

**验证步骤：**
1. 浏览器打开 Web UI，切换到「📊 进度」Tab
2. 查看网络请求：是否向 `/api/chat?channel=_admin` 发请求
3. 在 `_admin` 频道手动发送一条以 `📊` 开头的消息（通过任意 agent）
4. 刷新进度 Tab，观察是否显示
5. 插入一条虚假的 📊 格式消息到 `_admin` 频道数据库：`📊 R41 编码: SUBMITTED → WORKING`
6. 刷新页面，观察进度 Tab 是否渲染该消息

**期望结果：**
- 进度 Tab 显示「暂无任务进度数据」✅
- `/api/chat?channel=_admin` 返回空列表 ✅
- 手动注入 📊 消息后，进度 Tab 正确渲染 ✅（确认数据源为 `_admin` 频道）

**验收标准：** C-1, C-2, C-3, C-4 根因确认

---

## 方向 D — 点名流程拆解 + 多点点名

### V-D1 — 创建工作室后成员频道不自动切换

**目标：** 确认 `!create_workspace` 不自动切换全体成员活跃频道

**前置条件：**
- 开发环境运行中
- 管理员在线

**验证步骤：**
1. 管理员发送 `!create_workspace R41-Demo --members <member-a>,<member-b>`
2. 检查创建者的活跃频道：`persistence.get_agent_channel(sender_id)`
3. 检查成员 A 和 B 的活跃频道：是否仍为 `lobby`（或之前的频道）
4. 检查成员 A/B 是否收到 `MSG_SET_ACTIVE_CHANNEL` 消息
5. 检查 `_auto_rollcall_notify` 发送的消息内容

**期望结果：**
- 创建者频道切换到工作室 ✅
- 成员频道**未**切换（保持 `lobby`）✅（当前行为符合 D-1）
- 成员收到「📋 点名报道」通知，但不是频道切换指令 ✅
- 点名通知内容：无结构化上下文信息（仅文字）

**验收标准：** D-1 待验证 — 当前行为是否符合 D-1 需评审

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:397-428` | `_cmd_create_workspace()` — 创建者频道切换(line 420)，成员不动 | ⏳ 待验证 |
| `server/handler.py:283-315` | `_auto_rollcall_notify()` — 仅发送通知消息 | ⏳ 待验证 |
| `server/handler.py:1781-1800` | WebSocket 批准路径 — 仅绑定拥有者 | ⏳ 待验证 |
| `server/workspace.py:274-310` | `create_workspace()` — 创建 + 成员表，无频道操作 | ⏳ 待验证 |

---

### V-D2 — 点名消息能否指定目标角色

**目标：** 确认当前点名流程是否支持「指定单一角色」而非全员广播

**验证步骤：**
1. 检查 `_auto_rollcall_notify` 的成员列表来源
2. 检查点名消息模板：`handler.py:300-305`
3. 检查 `!rollcall` 命令处理逻辑：`handler.py:1338-1373`

**期望结果：**
- 当前 `_auto_rollcall_notify` 通知**所有**成员，不支持指定角色 ✅
- `!rollcall` 命令也切换**全体**成员频道，不支持指定 ✅
- 当前行为**不符合** D-2（点名需要指定目标角色）❌

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:291-310` | `_auto_rollcall_notify` — 遍历 `members` 全员广播 | ❌ 不符合 D-2 |
| `server/handler.py:1355-1363` | `!rollcall` — `for member_id in member_ids` 全员切换 | ❌ 不符合 D-2 |
| `server/handler.py:1096-1114` | 「已切」确认 — 检查 `_rollcall_confirmed` 全员确认 | ⏳ 待验证 |

---

### V-D3 — 点名后成员收到上下文

**目标：** 确认点名后关键成员是否能收到完整的上下文信息

**验证步骤：**
1. 管理员执行 `!create_workspace R41-Test --members <dev-bot>`
2. 观察 dev-bot 收到的点名消息内容
3. 检查点名消息是否包含：
   - 当前 Step 描述
   - 任务/背景信息
   - 上下文链接或引用
4. 确认点名消息存储到工作室频道或 `_admin` 频道

**期望结果：**
- 当前点名消息仅为「📋 点名报道 / 工作室已创建...」✅
- **不包含**任何结构化上下文信息 ❌
- **不符合** D-5（点名确认后需收到上下文）❌

**验收标准：** D-5 不满足

---

### V-D4 — 点名后消息落入工作室而非大厅

**目标：** 确认点名确认后成员的消息正确路由到工作室频道

**前置条件：**
- 工作室已创建
- 成员已通过 `!rollcall` 切换频道

**验证步骤：**
1. 成员回复「已切」确认
2. 成员发送一条消息
3. 检查 `handle_broadcast` 的 `channel` 变量解析
4. 检查消息是否写入工作室频道的 DB 和日志
5. 检查大厅日志是否包含此消息

**期望结果：**
- `channel` 解析为工作室 ID ✅（当前行为正确）
- 消息写入工作室 DB 和日志 ✅
- 大厅日志无此消息 ✅

**验收标准：** D-6 当前满足 ✅

**关键路径 / 代码追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `server/handler.py:855` | `channel = ... persistence.get_agent_channel(sender_id)` | ✅ 正常 |
| `server/handler.py:946-969` | 频道解析 → workspace 路由 | ✅ 正常 |
| `server/handler.py:978-1116` | 工作室消息 → 写入 DB → 广播 → write_chat_log | ✅ 正常 |

---

### V-D5 — 多点点名流转链路

**目标：** 评估完成一步后自动点名下一角色的方案可行性

**验证步骤：**
1. 检查当前 `_auto_rollcall_notify` 可否在任意 Step 完成后被复用
2. 检查 handler.py 中是否有「Step 完成触发」的钩子机制
3. 检查 `_admin` 命令执行后是否有回调/事件机制
4. 评估将 `_auto_rollcall_notify` 改造为 `_rollcall_next(ws_id, target_role, context)` 的改动范围

**期望结果：**
- 当前无「干完触发下一步」机制 ✅
- 需要新增命令：`!rollcall_next <target_role> --context <summary>` ✅
- `_rollcall_next` 可复用 `!rollcall` 的频道切换逻辑，但只切换单目标 ✅

**验收标准：** D-7, D-8 当前不满足

---

## Part B — 条件性修复方案

> 以下修复方案**仅**在 Part A 验证发现异常时触发。如果验证通过，跳过所有对应 FIX。

---

### FIX-A1 — 新增 WS_ENV 环境变量 + config.py 读取

**触发条件：** V-A2 验证发现生产环境仍显示绑定码，或 V-A3 确认无环境切换机制

**诊断步骤：**
1. 确认 `server/config.py` 无 `ENV`/`WS_ENV` 变量
2. 确认 `server/templates.py` 无条件渲染逻辑
3. 确认 `server/web_viewer.py` `setup_routes()` 无条件注册

**修复方案（推荐方案 A）：**

#### 方案 A — 配置层：新增 `WS_ENV`（推荐，4 行改动）

在 `server/config.py` 新增：

```python
# server/config.py — 环境区分
WS_ENV = os.environ.get("WS_ENV", "development").lower()
IS_PRODUCTION = WS_ENV == "production"
```

**改动用：** `server/config.py` — 新增 2 行

#### 方案 B — 模板层：条件渲染绑定码区域（推荐，8 行改动）

`server/templates.py` — 将静态 `BIND_TEMPLATE` 改为动态字符串：

```python
# BIND_TEMPLATE 改为动态生成函数
def get_bind_template(is_production: bool = False) -> str:
    bind_section = "" if is_production else """
    <p>请将下方绑定码<br>通过 Telegram 私聊发给 <strong>项目管理</strong> 进行授权</p>
    <div class="code-box" id="bindCode">--</div>
    <div class="status wait" id="status">
      <span class="spinner"></span>等待授权中...
    </div>
    <hr style="border:none;border-top:1px solid #30363d;margin:20px 0;">
    """
    # ... rest of template with {bind_section} placeholder
```

`server/web_viewer.py` — 在 `handle_chat()` 中传入 `is_production`：

```python
# server/web_viewer.py 的 handle_chat 中
is_prod = config.IS_PRODUCTION
template = get_bind_template(is_prod)
```

**改动用：** `server/templates.py` — 约 8 行改动, `server/web_viewer.py` — 约 2 行

#### 方案 C — 路由层：条件性注册绑定 API（可选，2 行改动）

`server/web_viewer.py` — `setup_routes()` 中：

```python
def setup_routes(app: web.Application) -> None:
    app.router.add_get("/", handle_chat)
    app.router.add_get("/chat", handle_chat)
    if not config.IS_PRODUCTION:
        app.router.add_get("/api/bind", handle_api_bind)
        app.router.add_get("/api/check", handle_api_check)
    # ... rest unchanged
```

**改动用：** `server/web_viewer.py` — ~2 行

#### 推荐执行顺序

> 方案 A + B + C = 约 12 行改动。推荐全部实施以确保生产环境安全。
> 方案 C 可选（隐藏路由比运行时返回 404 更安全，但需要重启）。

---

### FIX-B1 — 消除 save_message 双写（服务端去重）

**触发条件：** V-B1 确认双写，V-B2 确认前端去重无法彻底解决

**诊断步骤：**
1. 确认 `save_message()` 在 `handle_broadcast` 工作室内路径 line 1020 调用
2. 确认 `write_chat_log()` 在 line 1094 额外调用 `save_message()`
3. 确认 `INSERT OR IGNORE` 因 UUID 主键永不命中

**修复方案：**

#### 方案 B1 — 消除 write_chat_log 中的 save_message 调用（推荐）

`server/web_viewer.py` — `write_chat_log()` 中：

```python
def write_chat_log(sender_name: str, content: str, channel: str = "lobby") -> None:
    """写入聊天日志，推送 WS 消息。不保存到 message_store（由调用方处理）。"""
    # ❌ 删除: ms.save_message(...) — 调用方已保存
    # 仅保留: 写日志文件 + WS 推送
```

但需注意：`write_chat_log` 被多处调用，部分路径（如 `handler.py:998` 无在线成员时）**没有**前置 `save_message()`。需要在这些调用点补上 `save_message()`。

**改动用：** `server/web_viewer.py:35-91` — 移除 `ms.save_message()` 调用（~3 行）
**补碰文件：** `server/handler.py:998` — 确认离线路径已有 `save_message()` 或补上

#### 方案 B2 — 使用 msg_id 去重（替代方案）

保持双写不变，但在 `message_store.py` 中改用 **内容哈希** 代替 UUID 作为 `msg_id`：

```python
# message_store.py save_message()
msg_id = hashlib.sha256(f"{channel}|{ts:.0f}|{from_name}|{content}".encode()).hexdigest()[:16]
```

这样 `INSERT OR IGNORE` 真正生效——同一秒内同频道同内容的重复写入会被忽略。

**缺点：** 变更 `msg_id` 生成方式，可能影响已有消息的 ID 引用。

#### 推荐执行顺序

> 方案 B1（消除双写）为根因修复，方案 B2（哈希去重）为兜底。
> 推荐 B1 + B2 配合：消除冗余调用 + 哈希 msg_id 作为最后防线。

---

### FIX-C1 — 在 _cmd_task_create/_cmd_task_update 中调用 _broadcast_task_notify

**触发条件：** V-C1 确认 `_broadcast_task_notify` 零调用

**修复方案：**

#### 方案 C1 — _cmd_task_create + _cmd_task_update 末尾追加 notify（推荐，3 行）

```python
# handler.py _cmd_task_create 末尾（line 629-632 之前）
await _broadcast_task_notify(task, "SUBMITTED → WORKING")
```

```python
# handler.py _cmd_task_update 末尾（line 678 之前）
await _broadcast_task_notify(task, f"{current.value} → {target.value}")
```

**改动用：** `server/handler.py` — `_cmd_task_create` line 628 后追加 1 行, `_cmd_task_update` line 675 后追加 1 行

#### 方案 C2 — _broadcast_task_notify 同时写入 _admin chat log（推荐，3 行）

在 `_broadcast_task_notify` (handler.py) 末尾追加：

```python
# handler.py _broadcast_task_notify 末尾 line 843 前
notify_text = f"📊 {context_id} {task['name']}: {transition}"
write_chat_log("系统", notify_text, channel=p.ADMIN_CHANNEL)
```

**改动用：** `server/handler.py` — `_broadcast_task_notify()` 追加 2 行

> 注意：`write_chat_log` 在 `web_viewer.py`，需确保导入。通过浏览器 `renderProgressTab` → 30 秒轮询 → `GET /api/chat?channel=_admin` 即可获取。

#### 推荐执行顺序

> C1 + C2 = 约 6 行改动，完整修复进度 Tab 空白问题。
> 无需改动前端 `renderProgressTab()`——它正确地从 `_admin` 频道拉取 📊 消息，只是之前没有数据写入。

---

### FIX-D1 — 点名流程拆解

**触发条件：** V-D1 或 V-D2 确认成员频道切换无法指定角色

**诊断步骤：**
1. 确认 `!create_workspace` 创建后成员频道不切换（V-D1 结论）
2. 确认 `!rollcall` 切换全员而非指定角色（V-D2 结论）
3. 确认 `_auto_rollcall_notify` 发送全员通知（V-D1 结论）

**修复方案：**

#### 方案 D1 — 新增 !rollcall_role 命令（推荐，~40 行）

在 `handler.py` 新增命令：只在点名时切换**指定角色**的频道，而非全员。

```python
# handler.py — 新增命令
async def _cmd_rollcall_role(sender_id: str, params: dict) -> str:
    """点名指定角色的成员。用法：!rollcall_role <role_name> [--context <msg>]"""
    target_role = params.get("_raw", "").split()[0] if params.get("_raw") else ""
    # ...
    # 查找该角色的成员
    users = auth.get_users()
    targets = [aid for aid, u in users.items() if u.get("role") == target_role]
    # 只切换目标角色的频道
    for member_id in targets:
        persistence.set_agent_channel(member_id, ws_id)
        # 发送 MSG_SET_ACTIVE_CHANNEL
    # 只有目标角色需要回复
    _rollcall_expected[ws_id] = set(targets)
    # 发送带上下文的点名消息
    context = params.get("context", "")
    # ...
```

**注册命令：**

```python
"rollcall_role": {
    "handler": _cmd_rollcall_role, "min_role": 3, "workspace_scope": True,
    "usage": "!rollcall_role <role> [--context <上下文信息>]",
}
```

**改动用：** `server/handler.py` — 新增函数 ~35 行 + 命令注册 4 行

#### 方案 D2 — 改造 _auto_rollcall_notify 支持上下文传递

```python
# handler.py — _auto_rollcall_notify 改造
async def _auto_rollcall_notify(ws_id: str, sender_name: str, 
                                 target_role: str = "", context: str = "") -> None:
    """指定 target_role 时仅通知该角色，否则通知全员"""
    if target_role:
        users = auth.get_users()
        member_ids = [aid for aid, u in users.items() if u.get("role") == target_role]
    # ... rest unchanged
```

#### 推荐执行顺序

> D1（`!rollcall_role`）+ D2（上下文传递改造）= 约 50 行改动。
> 保留现有 `!create_workspace` → `_auto_rollcall_notify` 旧路径以向后兼容。

---

### FIX-D2 — 多点点名自动流转

**触发条件：** V-D5 确认无 Step 完成触发机制

**修复方案：**

#### 方案 D — 新增 !rollcall_next 命令（推荐，~30 行）

```python
async def _cmd_rollcall_next(sender_id: str, params: dict) -> str:
    """点名下一步的关键角色。用法：!rollcall_next <role> --context <上一Step 产出摘要>"""
    target_role = ...
    context = params.get("context", "")
    # 1. 获取角色对应的 agent_id
    # 2. 切换目标频道的活跃频道
    # 3. 发送带上下文的消息给目标
    # 4. 等待「已切」确认（只等待目标角色）
```

**改动用：** `server/handler.py` — 新增 ~30 行

**设计要点：**
- `--context` 需要包含上一个 Step 的产出摘要（commit hash、文件路径、关键决策）
- 点名消息格式：`📋 @dev-bot，请确认到位。你的任务：实现功能 X。上一 Step 产出：...`
- 目标频道自动切换为工作室 ID
- 接收人回复「已切」→ 确认到位

---

## 附录 A：本轮已合入 dev 的修复

| Commit | 内容 |
|:-------|:-----|
| — | 本轮尚无代码合入 |

## 本方案可能触发的改动（条件性）

| FIX | 文件 | 最大改动量 | 条件 |
|:----|:-----|:----------:|:----:|
| FIX-A1 | `server/config.py` | 2 行 | V-A2 ❌ |
| FIX-A2 | `server/templates.py` + `server/web_viewer.py` | 10 行 | V-A2 ❌ |
| FIX-B1 | `server/web_viewer.py` + `server/handler.py` | 6 行 | V-B1 ❌ |
| FIX-C1 | `server/handler.py` | 4 行 | V-C1 ❌ |
| FIX-C2 | `server/handler.py` | 2 行 | V-C1 ❌ |
| FIX-D1 | `server/handler.py` | 50 行 | V-D1/V-D2 ❌ |
| FIX-D2 | `server/handler.py` | 30 行 | V-D5 ❌ |

## 附录 B：双入口同步检查表

| 改动文件 | handler.py | __main__.py | entrypoint.py |
|:---------|:----------:|:-----------:|:-------------:|
| FIX-A (config.py) | 无需改动 ✅ | 无需改动 ✅ | 环境变量传递 ✅ |
| FIX-A (templates.py) | 仅 web_viewer.py 调 ✅ | 无需改动 ✅ | 无需改动 ✅ |
| FIX-B (write_chat_log) | 调用方，确认离线路径 ✅ | 无需改动 ✅ | 无需改动 ✅ |
| FIX-C (_broadcast_task_notify) | `_cmd_task_*` 触发 ✅ | 已有 relay 逻辑（line 614-626）✅ | 无需改动 ✅ |
| FIX-D (rollcall_role) | 新增命令，仅 handler.py ✅ | 无需改动 ✅ | 无需改动 ✅ |
| FIX-D (rollcall_next) | 新增命令，仅 handler.py ✅ | 无需改动 ✅ | 无需改动 ✅ |

## 附录 C：验证结果记录表

| V-# | 验证项 | 结果 | 备注 |
|:---:|:-------|:----:|:-----|
| V-A1 | 开发环境：绑定码+OAuth 显示 | ⬜ | |
| V-A2 | 生产环境：仅 OAuth，无绑定码 | ⬜ | |
| V-A3 | 环境切换通过配置 | ⬜ | |
| V-B1 | 双写根因：save_message+write_chat_log | ⬜ | |
| V-B2 | 前端去重哈希表验证 | ⬜ | |
| V-B3 | 前端双流重复验证 | ⬜ | |
| V-B4 | 长时间使用去重稳定性 | ⬜ | |
| V-C1 | _broadcast_task_notify 调用验证 | ⬜ | |
| V-C2 | MSG_TASK_NOTIFY → _admin 写入路径 | ⬜ | |
| V-C3 | 前端 renderProgressTab 数据来源 | ⬜ | |
| V-D1 | 创建工作室后成员频道不自动切换 | ⬜ | |
| V-D2 | 点名消息指定目标角色 | ⬜ | |
| V-D3 | 点名后成员收到上下文 | ⬜ | |
| V-D4 | 点名后消息落入工作室而非大厅 | ⬜ | |
| V-D5 | 多点点名流转链路评估 | ⬜ | |

> ✅ 通过 / ❌ 不通过 / ⏭️ 跳过 / ⬜ 未执行
