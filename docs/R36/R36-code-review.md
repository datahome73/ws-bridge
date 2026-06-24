# R36 代码审查报告 — Step 5

> **审查人：** 🔍 小周
> **日期：** 2026-06-23
> **审查对象：** `origin/r36` 分支 commit `1fcf5b52`
> **依据：** `docs/R36/R36-tech-plan.md` v1.0 ✅ + `docs/R36/R36-requirements.md` v1.0 ✅

---

## 审查结论

> **结论：** 🔴 **驳回 — 退回 Step 4 修复**
>
> 共发现 **7 个缺陷级问题（🔴）**、**4 个警告（🟡）**、**2 个建议（💡）**。
>
> 方向 B 消息内容与需求定稿完全不符（文案格式、emoji 使用、持久化方式均偏离定稿）。方向 D 核心方案（D-1 `ms.save_message` 移入 `write_chat_log`）正确，但 D-2 跨天回溯因 `handle_api_chat()` fallback 未同步更新而实际不生效。B-4（管理员审批确认通知）完全缺失。
>
> **修复后再提交审查 → 转 Step 6 测试验证。**

---

## 审查范围

| 文件 | 审查重点 | 结论 |
|:----|:--------|:----:|
| `server/handler.py` (+60) | 方向 B：注册欢迎消息(B-1)、管理员通知(B-2)、审批回执(B-3/B-4) | 🔴 驳回 |
| `server/web_viewer.py` (+70/-24) | 方向 D：`ms.save_message()`统一入口(D-1)、跨天日志回溯(D-2) | 🟡 条件通过 |

---

## 逐项审查

### 方向 B — 内部注册流程完善

#### B-1：新 bot 注册频道欢迎消息
- **位置：** `handler.py` L183–L193
- **判定：** 🔴 **驳回**
- **问题：**
  1. ❌ 使用 `_send(ws, ...)` 直接推送 WS 而非 `write_chat_log()`，消息不入日志/DB/Web UI
  2. ❌ 消息含 emoji（👋），违反需求定稿「纯文本格式，无 Markdown、无 emoji 系统图标」
  3. ❌ 文案与需求附录定稿完全不符：定稿要求 4 行 `[系统]` 前缀消息（含配对码有效期 + 等待提示 + status 查询指引），代码仅 2 行无前缀
  4. ❌ 缺少 3 分钟配对码有效期提醒
  5. ❌ 标签写「R32」应为「R36」

#### B-2：管理员新注册通知
- **位置：** `handler.py` L194–L210
- **判定：** 🔴 **驳回**
- **问题：**
  1. ❌ 未使用 R35 已建立的 `_admin_msg()` / `_persist_admin_response()` 模式
  2. ❌ 仅 WS 推送不持久化（无 `write_chat_log()` 调用到 ADMIN_CHANNEL）
  3. ❌ emoji 错误（📋 ≠ 📬）
  4. ❌ 文案与需求定稿不符：应含时间戳 + agent_id + approve_pairing 指引
  5. ❌ 标签写「R32」应为「R36」

#### B-3：审批通过 → Bot 成功通知
- **位置：** `handler.py` L2024–L2036
- **判定：** 🔴 **驳回**
- **问题：**
  1. ❌ 使用 `_send(conn, ...)` 而非 `write_chat_log()`，不入日志/DB
  2. ❌ 文案含 emoji（✅🎉📋），与定稿不符
  3. ❌ 文案缺少 `[系统]` 前缀
  4. ❌ 标签写「R32」应为「R36」

#### B-4：管理员审批确认通知
- **位置：** `handler.py`（B-3 代码块后）
- **判定：** 🔴 **缺失**
- **问题：** 需求附录定稿和技术方案均明确要求，但未实现。需求文案：
  ```
  ✅ 注册完成 — agent: xxxx-xxxx 已移至大厅
  ```
  技术方案指定 `write_chat_log("系统", f"✅ {target_id[:20]} 注册完成", channel=p.ADMIN_CHANNEL)`

#### B-5：status 查询（P2 可选）
- **判定：** 💡 未实现（可接受，P2 可选）

---

### 方向 D — 部署历史持久化

#### D-1：`ms.save_message()` 移入 `write_chat_log()`
- **位置：** `web_viewer.py` L54–L68
- **判定：** 🟡 **条件通过**
- **问题：**
  1. ❌ `from_agent="web_log"` 写死，技术方案要求 `from_agent=sender_name`
  2. ❌ 标签写「R32」应为「R36」
  3. 🟡 bare `except Exception: pass`，建议加 logger.debug()
- **做得好的：** ✅ 核心架构正确 — 一处入口覆盖所有消息写入路径，所有调用方自动受益

#### D-2：跨天日志回溯 `read_channel_logs()`
- **位置：** `web_viewer.py` L89–L140
- **判定：** 🔴 **须修复**
- **问题：**
  1. 🔴 `handle_api_chat()` L235 仍调用 `read_today_log(channel)` → 别名到 `read_channel_logs(channel, days=1)`，跨天不生效。技术方案要求 `days=7`
  2. 🟡 去重 key 用 `(ts, sender, content)` 不含日期，跨天同时间同内容消息会被误判为重复
  3. ❌ 标签写「R32」应为「R36」
- **做得好的：** ✅ 函数签名支持参数化 `days`，去重逻辑合理，文件级迭代效率好

---

## 问题清单

| 级别 | 位置 | 问题 | 修复要求 |
|:----:|:-----|:-----|:--------|
| 🔴 | handler.py:183-193 | B-1：使用 `_send()` 而非 `write_chat_log()`，文案含 emoji / 与定稿不符 | 改用 `write_chat_log()` + 需求定稿文案 |
| 🔴 | handler.py:194-210 | B-2：未用 `_admin_msg()` 模式，文案与定稿不符 | 改用 `_persist_admin_response()` + 定稿格式 |
| 🔴 | handler.py:2024-2036 | B-3：使用 `_send()` 非 `write_chat_log()`，文案含 emoji | 改用 `write_chat_log()` + 定稿文案 |
| 🔴 | handler.py (after B-3) | **B-4 完全缺失** | 新增管理员确认通知 |
| 🔴 | web_viewer.py:235 | `handle_api_chat()` fallback 仍用 `read_today_log()` → days=1 | 改为 `read_channel_logs(channel, days=7)` |
| 🔴 | handler.py + web_viewer.py 多处 | 全部标签写「R32」应为「R36」 | 全局替换 R32→R36 |
| 🟡 | web_viewer.py:57 | D-1：`from_agent="web_log"` 应透传 sender_name | 改为 `from_agent=sender_name` |
| 🟡 | web_viewer.py:130 | D-2：去重 key 不含日期 | 在 dedup key 中加入 date_str |
| 🟡 | 所有新 try/except | bare `except Exception: pass` | 加 `logger.debug()` 记录被吞异常 |
| 💡 | handler.py | B-5 status 查询（P2 可选） | 酌情考虑 |
| 💡 | Docker 配置 | D-3 Dev 容器 volume | 独立 commit |

---

## 对齐检查

- [ ] 与技术方案一致 — ❌ 方向 B 消息格式/持久化偏离，方向 D cross-day fallback 未生效
- [ ] 验收标准全部覆盖 — ❌ B-4 缺失，B-1/B-2/B-3 文案不达标
- [ ] 向后兼容 — ✅ 纯新增分支，不修改已有逻辑
- [ ] 双入口同步 — ✅ 方向 B 只在 handler.py（WS 入口），方向 D 在 web_viewer.py（双入口共享）

---

## 修复要求汇总

1. **B-1/B-3**：消息改用 `write_chat_log()` + 需求定稿纯文本文案（无 emoji、`[系统]` 前缀、4 行完整信息）
2. **B-2**：使用 `_persist_admin_response()` 发送 + 需求定稿格式（📬、agent_id、时间戳、approve_pairing 指引）
3. **B-4（新增）**：审批通过后 `write_chat_log()` 写管理员确认通知到 ADMIN_CHANNEL
4. **D-2**：`handle_api_chat()` 改为 `read_channel_logs(channel, days=7)`
5. **全部 R32 → R36** 标签替换
6. **D-1** `from_agent="web_log"` → `from_agent=sender_name`
7. **D-2** dedup key 加入日期前缀
8. **异常处理**：bare except 补 logger.debug()

---

> **审查结论：** 🔴 **驳回** → 退回 Step 4 编码修复，修复后提交再次审查 → 通过后转 🦐 泰虾 部署测试
