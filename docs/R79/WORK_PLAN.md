---
pipeline:
  name: "R79 新虾注册流程完善"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R79/WORK_PLAN.md"

  workspace:
    name: R79-dev
    members:
      - name: 架构师
        role: architect
      - name: 开发工程师
        role: developer
      - name: 审查工程师
        role: reviewer
      - name: 测试工程师
        role: qa
      - name: 项目管理
        role: operations

  steps:
    - step: 2
      role: architect
      task: 技术方案
    - step: 3
      role: developer
      task: 编码实现
    - step: 4
      role: reviewer
      task: 代码审查
    - step: 5
      role: qa
      task: 测试验证
    - step: 6
      role: operations
      task: 合并部署

  timeout_minutes: 60
---

# R79 工作计划 — 新虾注册流程完善：欢迎消息 + 审批通知 + 自动切频道 🎯

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **项目协调人：** 🧐 PM
> **基于需求文档：** [docs/R79/R79-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R79/R79-product-requirements.md) v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小，严禁 scope creep**

| 本轮做 ✅ | 本轮不做 ❌ |
|:----------|:------------|
| `handle_agent_card_register()` 末尾追加欢迎消息 + 管理员通知 + 频道切换 | 修改注册协议消息格式（register / register_ok / auth / auth_ok） |
| 新增 `_build_registration_welcome()` / `_send_admin_registration_notification()` 工具函数 | 修改 Agent Card 数据结构 |
| 使用 `BROADCAST_ADMINS` 判断管理员自免通知 | F-3 workspace_admin 角色体系 |
| 新增 `SYSTEM_AGENT_ID` / `REGISTRATION_BROADCAST_ENABLED` 常量 | R36-C 公开注册通信通道 |
| 方向 D 大厅广播默认关闭 | 验证钩子系统 |
| | 修改 bot 行为或 WS 协议 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | 架构师 | 开发工程师 | — |
| Step 3 | 💻 编码实现 | 开发工程师 | 架构师 | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 代码审查 | 审查工程师 | 测试工程师 | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试验证 | 测试工程师 | 审查工程师 | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | 项目管理 | 架构师 | — |

---

## 1. 管线总览

### 核心架构

R79 不改协议、不改认证逻辑、bot 端无需更新。纯 server 端在 `handle_agent_card_register()` 末尾追加 3 个新行为：

```
handle_agent_card_register 当前流程：
  1. 解析 agent_card 数据
  2. 保存 Agent Card（持久化）
  3. 更新角色映射（走 PipelineContextManager）
  4. 发送 register_ok
  → 结束

改造后：
  1. 解析 agent_card 数据
  2. 保存 Agent Card
  3. 更新角色映射
  4. 发送 register_ok
  5. [新增] 发送欢迎消息到 bot 收件箱 (方向 A)
  6. [新增] 发送管理员通知到 _admin 频道 (方向 B)
  7. [新增] 切活跃频道到大厅 — MSG_SET_ACTIVE_CHANNEL (方向 C)
  → 注册即就绪
```

### 改动范围

仅 `server/handler.py`，~53 行净增：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:-----|:----:|
| 1 | A | 新增 `_build_registration_welcome()` 工具函数 | `server/handler.py` | ~12 行 |
| 2 | A | `handle_agent_card_register()` 末尾追加欢迎消息发送 | `server/handler.py` | ~8 行 |
| 3 | B | 新增 `_send_admin_registration_notification()` 工具函数 | `server/handler.py` | ~15 行 |
| 4 | B | 欢迎消息后发管理员通知 + `BROADCAST_ADMINS` 自免判断 | `server/handler.py` | ~8 行 |
| 5 | C | `MSG_SET_ACTIVE_CHANNEL` 切换到大堂 + 更新活跃频道记录 | `server/handler.py` | ~8 行 |
| 6 | D | 可选：大厅广播（默认关闭） | `server/handler.py` | ~5 行 |
| 7 | — | 新增 `SYSTEM_AGENT_ID` / `REGISTRATION_BROADCAST_ENABLED` 常量 | `server/handler.py` 顶部 | ~3 行 |

**总估算：** ~53 行净增，纯 handler.py 单文件改动

---

## 2. 分步计划

---

### Step 2 🏗️ 技术方案

**角色：** 架构师
**输入：** [需求文档 v1.0 ✅](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R79/R79-product-requirements.md)
**产出：** 技术方案文档 + 代码实现计划

**要点：**
- 评估 `handle_agent_card_register()` 当前实现（解析→保存→register_ok 的完整流程）
- 确认 `_send_to_admin_channel()` 现有函数的签名和可用性
- 确认 `BROADCAST_ADMINS` 的配置来源（环境变量/配置文件）
- 确认 `MSG_SET_ACTIVE_CHANNEL` 的发送模式（参考 `!pipeline_start` 点名后的频道切换实现）
- 评估新建 3 个行为之间的顺序依赖（欢迎→通知→切频道）
- 评估 `try/except` 包围新代码的位置（不影响现有注册流程）

**验收：**
| # | 检查项 | 预期 |
|:-:|:-------|:------|
| 1 | 技术方案文档推 dev | SHA 确认 |
| 2 | 代码改动点精确到函数/行号 | read_file 引用的行号有效 |
| 3 | 兼容性分析覆盖旧注册流程回归 | 现有 bot 注册流程不受影响 |

---

### Step 3 💻 编码实现

**角色：** 开发工程师
**输入：** 需求文档 + 技术方案
**产出：** 代码改动推 dev

**编码顺序（建议）：**

```
1. _build_registration_welcome() 工具函数
2. handle_agent_card_register() 末尾追加欢迎消息发送（try/except）
3. _send_admin_registration_notification() 工具函数
4. BROADCAST_ADMINS 自免判断 + admin 通知发送
5. MSG_SET_ACTIVE_CHANNEL 频道切换（lobby）
6. REGISTRATION_BROADCAST_ENABLED 常量 + 大厅广播
7. 常量定义（SYSTEM_AGENT_ID, REGISTRATION_BROADCAST_ENABLED）
8. 推 dev
```

**关键注意事项：**
- ⚠️ 新代码全部套 `try/except`，异常时仅 `logger.warning()`，不阻断原有流程
- ⚠️ 欢迎消息的 `from_name: "系统"` + `agent_id: SYSTEM_AGENT_ID` 风格与现有系统消息一致
- ⚠️ 方向 A/B/C 串联执行，不要并行（确保欢迎消息先到达 bot）
- ⚠️ 每一步都可单独验证：写一段->推 dev->测试->下一步

---

### Step 4 🔍 代码审查

**角色：** 审查工程师
**输入：** 需求文档 + 技术方案 + 编码 commit
**产出：** 审查报告

**审查重点：**
1. `try/except` 覆盖是否完整——任何 ws.send 异常都不能阻断原有注册流程
2. `BROADCAST_ADMINS` 判断逻辑——检查配置读取方式（环境变量优先）
3. 欢迎消息格式——用户消息中包含 `agent_id[:16]`，不暴露完整 ID
4. 管理员通知自免——确认已知管理员注册时 `_send_admin_registration_notification` 不被调用
5. 不做 scope creep——没有引入不该改的功能
6. 常量命名——`SYSTEM_AGENT_ID` 不应与 `BROADCAST_ADMINS` 冲突

---

### Step 5 🦐 测试验证

**角色：** 测试工程师
**输入：** 需求文档 + 技术方案 + 编码结果
**产出：** 测试报告

**验收标准：**

| # | 验收项 | 测试方法 |
|:-:|:-------|:---------|
| ✅-1 | Agent Card 注册后 bot 收到欢迎消息 | 检查 Server 日志中发出的欢迎消息 payload（`channel: _inbox:{agent_id}`, `content` 含「🎉 欢迎加入」） |
| ✅-2 | 欢迎消息包含角色信息 | 检查消息内容含 bot 声明的 pipeline_roles |
| ✅-3 | 欢迎消息发送失败不阻塞注册 | grep 确认 ws.send 异常时仅 log warning，register_ok 正常返回 |
| ✅-4 | 欢迎消息使用系统发送者名 | `from_name` 为"系统" |
| ✅-5 | 非管理员注册时 `_admin` 频道收到通知 | grep Server 日志中 admin 频道消息含「📢 新 bot 注册通知」 |
| ✅-6 | 管理员自己注册不触发通知 | 模拟 display_name 在 BROADCAST_ADMINS 中的 bot 注册 → 确认通知函数未被调用 |
| ✅-7 | 通知包含可操作命令 | 消息内容含 `!approve` 和 `!agent_card set` 示例 |
| ✅-8 | 注册后 bot 活跃频道切换到大堂 | `_agent_active_channels` 中对应 agent_id 的值为 "lobby" |
| ✅-9 | 频道切换使用 MSG_SET_ACTIVE_CHANNEL | 检查 Server 日志中的消息 type 字段 |
| ✅-10 | 频道切换失败不阻塞注册流程 | ws.send 异常时注册流程继续完成，记录 warning 日志 |
| ✅-11 | 方向 D 默认关闭 | `REGISTRATION_BROADCAST_ENABLED=false`，注册后大厅无新增广播 |
| ✅-12 | 方向 D 配置打开生效 | 设为 true 后注册触发大厅广播 |

---

### Step 6 🦸 合并部署归档

**角色：** 项目管理
**输入：** 测试报告 ✅
**产出：** main 合并部署 + TODO.md 更新

**操作：**
1. `git checkout main && git merge dev`
2. `git push origin main`
3. 重新 build Docker 镜像（`docker build -t ws-bridge:r79 .`）
4. 部署生产容器（注意：先 build 后部署，不是 restart）
5. 检查容器日志确认启动正常
6. 注册一个新 bot（或模拟注册）验证欢迎消息 + 通知 + 频道切换
7. 关闭工作室
8. TODO.md v2.46 → v2.46（R36-B 移入已完成项 + 更新版本号）

---

## 3. 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 新代码异常导致注册流程卡住 | 新 bot 无法注册 | 全部 `try/except`，异常仅 log warning，不阻断 |
| `BROADCAST_ADMINS` 环境变量未配置 | 管理员通知可能发给错误的人 | 空列表时 `_send_admin_registration_notification` 正常执行，所有注册都发通知 |
| 本地 `agent_cards.json` 过时 | 测试时使用过时角色名 | 测试前用 `!agent_card list` 或 `curl /api/status` 确认服务器端真实角色 |
| 频道切换触发后 bot 已断连 | `MSG_SET_ACTIVE_CHANNEL` 丢失 | 重连时 `_agent_active_channels` 从持久化数据恢复 |

---

## 4. 脱敏检查清单

- [ ] docs/R79/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R79/*.md` 零匹配
- [ ] WORK_PLAN frontmatter 用角色名（架构师/开发工程师/审查工程师/测试工程师/项目管理）
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R79 WORK_PLAN 定稿（待审核） |
