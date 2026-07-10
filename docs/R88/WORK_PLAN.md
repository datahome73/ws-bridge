---
pipeline:
  name: "R88 Pipeline AutoRouter — PM 的自动派活工具 🚂"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R88/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R88/R88-product-requirements.md"

  topology:
    auto_chain: true
    chain:
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
      title: 合并部署归档

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "输出技术方案（含服务架构、角色映射策略、chain 解析）"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码实现 auto_router.py（~250 行）"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 auto_router.py（重点：断线重连、角色映射鲁棒性）"
      qa:
        mention_keyword: "qa;测试"
        rules: "输出测试报告（19 项验收 + 端到端场景）"
      operations:
        mention_keyword: "operations;运维"
        rules: "注册 AutoRouter 服务 + 部署 + 更新文档"
---

# R88 工作计划 — Pipeline AutoRouter 🚂

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R88/R88-product-requirements.md v3.0
> **日期：** 2026-07-10

---

## 0. 本轮行为规则（全体必读）

### 0.1 本轮定位：PM 的工具

**R88 本质是给 PM 开发一个自动派活工具。** 不是给 bot 改协议，不是改 server 核心路由，只是写一个独立服务来代理 PM 的重复性劳动。

> 就像给 PM 配了一个小助理：你完成 Step 1（写文档+启动管线），助理自动跑后续的「谁完成→找下一棒→派活」流程。

### 0.2 Scope 纪律

**创建一个新文件 `server/auto_router.py`，不修改 handler.py 一行代码。**

| ✅ 做 | ❌ 不做 |
|:------|:--------|
| 创建 `server/auto_router.py`（~250 行独立服务） | 修改 `handler.py` 的任何逻辑 |
| 通过 WebSocket 以 bot 身份连接 ws-bridge | 修改协议或消息路由 |
| 从 PM 收件箱解析转发通知 | 修改 `_inbox:server` 中继逻辑 |
| 从远程 WORK_PLAN.md 解析 frontmatter topology | 依赖 server 内存状态 `_PIPELINE_CONFIG` |
| 发 inbox 消息给目标 bot | 使用非标准消息格式 |
| 更新 TODO.md + inbox-message-protocol.md | 改动 Agent Card、Web 端、workspace |

### 0.3 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 方案≠编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者≠审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者≠测试者 ✅ |
| Step 6 | 🦸 合并部署+文档更新 | operations | architect | |

### 0.4 关键概念共识（全员必读）

**R88 的核心设计思路与之前的管线不同：**

| 概念 | 之前（手动模式） | R88（AutoRouter 自动模式） |
|:-----|:---------------|:--------------------------|
| PM 的角色 | 站在管线外，手动派活 | **PM 是 Step 1**，完成准备后启动管线 |
| `!pipeline_start` | 准备工作（创建 workspace） | **即 Step 1 完成信号** |
| Step 2 触发 | PM 手动发 `_inbox:arch` | AutoRouter 检测 Step 1 完成→自动派活 |
| 后续 Steps | PM 逐一手动派活 | AutoRouter 监听 PM 收件箱→自动链条式接力 |
| bot 的 `from_name` | `PM` | `系统(管线)`（bot 完全透明） |
| 手动模式兼容 | — | **不启动 AutoRouter 即可** |

**对开发者的提醒：** 这个工具不是藏在 server 内部逻辑里的，而是一个可以用 `--api-key` 参数启动的独立进程。它通过 WebSocket 连上 ws-bridge，用的就是普通 bot 的 API——发 inbox、收消息。所以：
- 不需要理解 handler.py 内部逻辑
- 不需要知道 `_PIPELINE_CONFIG` 怎么存的
- 只需要会用 `websockets` 库发/收消息 + 解析 frontmatter YAML

### 0.5 AutoRouter 的 api_key 说明

AutoRouter 需要自己的 ws-bridge api_key（作为 bot 身份连接）。这个 key 在部署时生成：
- 测试阶段：PM 暂用自己的 api_key 调试
- 生产阶段：由 operations 在部署时注册一个专用的 AutoRouter bot + key

---

## 1. 管线总览

### 1.1 核心通信流

```
PM (Step 1)                  ws-bridge Server           AutoRouter Service        Bot N
│                                  │                           │                    │
│① !pipeline_start R88 ...        │                           │                    │
│   (= Step 1 完成)               │                           │                    │
│                                  │── ② 管线就绪通知 ───────→│                    │
│                                  │                           │                    │
│                                  │                           │── ③ 派活 Step2 ──→│
│                                  │                           │    _inbox:arch     │
│                                  │  ←────────── ④ ACK ←─────│                    │
│                                  │          (_inbox:server/中继 →PM收件箱)         │
│                                  │                           │                    │
│                                  │                           │   [arch 干活中...] │
│                                  │                           │                    │
│                                  │  ←────────── ⑤ ✅ 完成 ←─│                    │
│                                  │          (_inbox:server/中继 →PM收件箱)         │
│                                  │                           │                    │
│ PM 收件箱收到 "✅ arch 完成"     │                           │                    │
│                                  │  ⑥ AutoRouter 检测完成   │                    │
│                                  │  → chain[0]→chain[1]     │                    │
│                                  │                           │── ⑦ 派活 Step3 ──→│
│                                  │                           │    _inbox:dev      │
│                                  │                           │                    │
│                      ... 以此类推到 Step 6 ...                               │
│                                  │                           │                    │
│                                  │                           │── ⑧ 全部完成通知 →│
│  ←── ⑨ 🏁 R88 全线闭环 ──────┤                           │                    │
```

### 1.2 PM 的手动备援

AutoRouter 启动后，PM 的收件箱仍然会收到 R87 中继的转发通知（ACK 转发和完成转发）。如果 AutoRouter 出问题：
1. **停掉 AutoRouter 进程**
2. **手动模式**：PM 继续按现有流程手动派活
3. **修复 AutoRouter**：修好后重启，它会恢复活跃管线进度并继续

**AutoRouter 出问题时，什么都不影响——PM 切回手动模式即可。**

---

## 2. Step 2 — 技术方案（arch）

### 2.1 任务

设计 `server/auto_router.py` 的技术方案。

### 2.2 需要确认的设计点

| # | 问题 | 建议方向 | 决策 |
|:--|:-----|:---------|:----:|
| 1 | **AutoRouter 的 api_key 注册流程** | 测试用 PM 的 key，生产注册专用 key | 由 PM 决策 |
| 2 | **角色映射策略** | 从 `!agent_card list` 查询 `pipeline_roles` → role→agent_id 映射 | arch 定 |
| 3 | **`_restore_pipeline_state` 实现** | `!pipeline_status` 查询 vs `_admin` 历史读取 | arch 定 |
| 4 | **`_fetch_topology` 具体实现** | 从 WORK_PLAN URL 下载 frontmatter vs 从 `!pipeline_status` 缓存 | arch 定 |
| 5 | **frontmatter 解析方案** | PyYAML 直接解析 vs 正则提取 | arch 定 |
| 6 | **多个活跃管线时 AutoRouter 行为** | 同时追踪所有活跃管线 vs 按 round_name 逐个 | arch 定 |
| 7 | **日志结构化** | JSON lines 日志 vs Python logging | arch 定 |
| 8 | **兜底：找不到 WORK_PLAN URL** | 从工作区特性推断 | arch 定 |

### 2.3 输出

`docs/R88/R88-tech-plan.md`，包含：
- 服务架构图（含模块划分）
- `PipelineAutoRouter` 类的完整伪代码（核心方法）
- 角色映射策略（如何从 Agent Card 找 role→agent_id）
- chain 解析策略（有限 YAML vs 全量 YAML）
- 模板变量替换策略
- 断线重连方案
- 错误处理方案
- 边界情况（多个活跃管线、管线中途重启 AutoRouter）

---

## 3. Step 3 — 编码实现（dev）

### 3.1 任务

根据技术方案编码实现 `server/auto_router.py`。

### 3.2 文件

- **新文件：** `server/auto_router.py`（~250 行）
- **无需修改：** `handler.py`、`config.py`、任何现有文件

### 3.3 类接口（参考）

```python
class PipelineAutoRouter:
    async def start(self)                        # 启动并保持连接
    async def _handle_message(self, msg: dict)   # 消息入口
    async def _on_pipeline_ready(self, round)    # 管线就绪
    async def _on_step_complete(self, content)   # Step 完成
    async def _dispatch_step(self, ...)          # 派活下一棒
    async def _notify_all_done(self, round)      # 全部完成
    async def _restore_pipeline_state(self)      # 启动恢复
    async def _fetch_topology(self, round)       # 读拓扑配置
    def _resolve_agent_id(self, role, round)     # 角色→agent_id
    def _extract_role(self, content)             # 解析角色
    def _extract_sha(self, content)              # 解析 SHA
    def _extract_round(self, content)            # 解析轮次
    async def _send_inbox(self, target_id, cnt)  # 发 inbox
    async def _send_to_pm(self, content)         # 通知 PM
```

### 3.4 关键实现细节

- **WebSocket 连接重用：** 在 `__aenter__` / `__aexit__` 或 `async with` 中保持连接
- **消息去重：** 通过 `msg.id` 或 `seen_ids` set 去重
- **安全：** 只监听 PM 收件箱，不监听其他频道
- **不依赖 server 内存状态：** 所有配置从远程 WORK_PLAN.md 读取

### 3.5 测试用命令（开发阶段）

```bash
# 手动启动测试
cd /opt/data/ws-bridge
python3 -m server.auto_router --api-key sk_ws_... --pm-agent-id ws_...

# 或指定 ws-url
python3 -m server.auto_router --api-key sk_ws_... --pm-agent-id ws_... --ws-url wss://wsim.datahome73.cloud/ws
```

---

## 4. Step 4 — 代码审查（review）

### 4.1 任务

审查 `server/auto_router.py`。

### 4.2 审查重点

| 审查点 | 优先级 | 说明 |
|:-------|:------:|:------|
| **断线重连** | 🔴 | ws 断线后能否自动重连并恢复状态？ |
| **角色映射鲁棒性** | 🔴 | role→agent_id 映射失败时不会 crash |
| **消息去重** | 🟡 | 同一条完成通知不会被处理两次 |
| **多活跃管线** | 🟡 | 同时 R88 和 R89 两个管线运行，能正确区分？ |
| **安全性** | 🔴 | 只监听 PM 收件箱，不误监听到 bot 私聊 |
| **异常处理** | 🔴 | 派活失败、YAML 解析失败、WS 发送失败→日志+通知 PM |
| **简写格式兼容** | 🟡 | `auto_chain: true` 但不写 `chain` 时能否正常工作 |

### 4.3 输出

`docs/R88/R88-code-review.md`，审查结论使用标准格式：
- 🟢 通过 / 🟡 条件通过 / 🔴 退回

---

## 5. Step 5 — 测试验证（qa）

### 5.1 任务

编写测试报告，验证 19 项验收标准覆盖。

### 5.2 测试场景

| # | 场景 | 前置条件 | 预期结果 |
|:-:|:-----|:---------|:---------|
| S1 | **标准 6-Step 自动接力** | 启动管线 + 启动 AutoRouter | arch→dev→review→qa→ops 自动接力，PM 不手动发任何消息 |
| S2 | **手动模式兼容** | 不启动 AutoRouter | 管线照常手动运行 |
| S3 | **AutoRouter 中途停止** | 启动 → 跑一半 → 停 AutoRouter | 管线不丢失，PM 切回手动继续 |
| S4 | **无 topology 定义** | 启动不含 topology 的管线 | AutoRouter 安静跳过 |
| S5 | **派活失败通知** | chain 中的 role 无对应 agent | PM 收到 ❌ 通知 |
| S6 | **SHA 提取** | 各种格式的 `✅ 完成` 消息 | 正确提取 SHA |

### 5.3 输出

`docs/R88/R88-test-report.md`，19 项验收逐项标注 🟢/🟡/🔴。

---

## 6. Step 6 — 合并部署归档（ops）

### 6.1 任务

1. `git checkout main && git merge dev`
2. `git push origin main`
3. 注册 AutoRouter 专用 api_key（或使用 PM 现有 key 启动测试）
4. 在 server 部署环境中安排 AutoRouter 启动方式：
   - docker-compose 加 `auto_router` 服务
   - 或 systemd service
   - 或手动 `nohup python3 -m server.auto_router ... &`
5. 更新 TODO.md（版本号 + 标记 ✅）
6. 更新 `docs/inbox-message-protocol.md` §8（补充 AutoRouter 服务模型）
7. 关闭工作室

### 6.2 部署后验证

```bash
# 1. 启动 AutoRouter
python3 -m server.auto_router \
  --api-key <api_key> \
  --pm-agent-id <pm_agent_id>

# 2. 检查日志：AutoRouter 已连接
#    "AutoRouter 已连接, agent_id=..."

# 3. 启动一个测试管线（含 topology）
#    检查 AutoRouter 是否检测到并自动派活 Step 2

# 4. 手动不启动 AutoRouter 验证手动模式兼容
```

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-10 | 初稿 |
