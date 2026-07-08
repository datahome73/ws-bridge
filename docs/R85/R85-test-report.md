# R85 全链路测试报告

> **版本：** v1.0
> **测试日期：** 2026-07-08
> **基线：** ws-bridge `main`（R83）
> **测试工具：** WS 直连脚本（`test_*.py`）
> **协议版本：** `docs/inbox-message-protocol.md` §8 标准全流程通信步骤

---

## 1. 测试范围

逐个测试 5 个 bot 的 inbox 双向通信能力。按照 `docs/inbox-message-protocol.md` §8 定义的 4 步标准流程：

```
Step 1: PM 派活到 bot 收件箱
Step 2: Bot 回复 ACK 到发件人收件箱
Step 3: Bot 处理完任务后回复完成消息
Step 4: PM 确认收到，闭环
```

---

## 2. 测试结果总表

| Bot | Step 1 派活 | Step 2 ACK | Step 3 完成回复 | Step 4 PM确认 | 结论 |
|:----|:-----------:|:----------:|:---------------:|:-------------:|:----:|
| **小开** | ✅ | ✅ 内容异常 | ❌ | — | ❌ B1 |
| **爱泰** | ✅ | ✅ 内容为错误信息 | ❌ | — | ❌ B2 |
| **小周** | ❌ | — | — | — | ❌ B3 |
| **泰虾** | ❌ | — | — | — | ❌ B4 |
| **小爱** | ✅ | ✅ 格式正确 | ❌ 未发送 | — | 🟡 B5 |

---

## 3. 逐项测试记录

### 3.1 小开

| 项 | 结果 | 详情 |
|:---|:----:|:------|
| 连通性 | ✅ | 消息送达，2s 内回复 |
| ACK 内容 | ❌ | `💾 Self-improvement review: User profile updated` |
| 完成回复 | ❌ | 未收到 |
| 推测根因 | `_inbox:小开` 被设为主通道，LLM 将任务消息当作普通聊天处理 |

### 3.2 爱泰

| 项 | 结果 | 详情 |
|:---|:----:|:------|
| 连通性 | ✅ | 消息送达，2s 内回复 |
| ACK 内容 | ❌ | `Context overflow and auto-compaction is disabled (compression.enabled: false)...` |
| 完成回复 | ❌ | 未收到 |
| 推测根因 | `compression.enabled: false`，上下文溢出时 LLM 直接输出错误信息而非正常 ACK |

### 3.3 小周

| 项 | 结果 | 详情 |
|:---|:----:|:------|
| 连通性 | ❌ | 60 秒完全无响应，服务端显示 1 连接在线 |
| ACK 内容 | — | 未收到任何消息 |
| 推测根因 | `mention_mode: true` 过滤了不带 `@小周` 的 inbox 消息，或 `on_message` 回调未处理 `_inbox:` 频道 |

### 3.4 泰虾

| 项 | 结果 | 详情 |
|:---|:----:|:------|
| 连通性 | ❌ | 60 秒完全无响应，服务端显示 3 连接在线 |
| ACK 内容 | — | 未收到任何消息 |
| 推测根因 | 同小周 — `mention_mode: true` 过滤或 `on_message` 未处理 `_inbox:` |

### 3.5 小爱

| 项 | 结果 | 详情 |
|:---|:----:|:------|
| 连通性 | ✅ | 消息送达 |
| ACK 内容 | ✅ | `ACK ✅ R85 全流程测试收到` — 格式正确，简洁 |
| 完成回复 | ❌ | 两次测试均未收到第二条消息 |
| Step 4 确认 | — | 因 Step 3 缺失未触发 |
| 推测根因 | LLM 将 ACK 和完成合并为一条消息发送，未分两条（先 ACK，处理完再发完成） |

---

## 4. Bug 清单

| Bug | Bot | 症状 | 优先级 |
|:---:|:----|:-----|:------:|
| F1 | 小谷 | `xiaogu_daemon.py` 自动回复 `"✅ 小谷已收到你的消息。"` 到 bot 收件箱 | ✅ 已修复 |
| B1 | 小开 | ACK 内容为 LLM 内部状态 `💾 Self-improvement review` | 🔴 P0 |
| B2 | 爱泰 | ACK 内容为 LLM 错误 `Context overflow` | 🔴 P0 |
| B3 | 小周 | 完全收不到 inbox 消息 | 🔴 P0 |
| B4 | 泰虾 | 完全收不到 inbox 消息（同 B3） | 🔴 P0 |
| B5 | 小爱 | 收到消息、ACK 格式正确，但未发送完成回复 | 🔴 P0 |

---

## 5. 修复建议

### 5.1 统一 Gateway 配置模板

所有 bot 需按以下标准配置：

```yaml
platforms:
  ws_bridge:
    enabled: true
    allow_all: true
    extra:
      mention_mode: false       # 不过滤关键词，所有 inbox 消息都处理
      mention_keyword: ''       # 不设触发词限制
      agent_id: ''              # 由 credential 文件自动获取
```

### 5.2 LLM 配置

```yaml
compression:
  enabled: true                 # 开启自动上下文压缩
```

### 5.3 消息处理逻辑

Bot 收到 `_inbox:` 消息后必须：

1. **立即**回复 ACK 到 `_inbox:<发件人agent_id>`（单独一条消息）
2. **处理完任务后**再发第二条完成回复到 `_inbox:<发件人agent_id>`
3. ACK 和完成回复必须是**两条独立消息**，不能合并
4. 回复**只包含结果**，不输出思考过程
5. 收到 PM 的 Step 4 确认后，**不再回复**

### 5.4 修复顺序

```
1. 小爱（格式已正确，补 Step 3 即可）→ 作为模板
2. 小周、泰虾（mention_mode → false）
3. 爱泰（compression.enabled → true）
4. 小开（主通道配置修正）
```

---

## 6. 参考文档

| 文档 | 用途 |
|:-----|:------|
| `docs/inbox-message-protocol.md` | 标准全流程通信步骤（4 步 SOP） |
| `docs/WORKSPACE_RULES.md` | 群聊规则（回复格式、说话礼仪） |
| `docs/R85/bug-log.md` | 详细 Bug 记录 |
