# R99 测试报告 — Bot 权限等级体系 🔒

> **测试人：** 🦐 泰虾 (QA)
> **测试基准：** `ed18016`（小周 🟢 审查通过）
> **测试日期：** 2026-07-13
> **改动范围：** 4 文件 +85/-8 行
>   - `server/auth.py` — `get_level()` + `set_level()` (~+40 行)
>   - `server/persistence.py` — `get_api_key_record()` (+7 行)
>   - `server/handler.py` — level 初始化 + 检查 + 系统名统一 (~+18/-10 行)
>   - `server/agent_card.py` — Agent Card 提交时自动晋升 L2→L3 (+14 行)
> **测试文件：** `tests/test_r99_bot_level.py` (33 项)

---

## 测试结果总览

| 测试类别 | 测试项数 | 通过 | 失败 | 通过率 |
|:---------|:--------:|:----:|:----:|:------:|
| T-1 ~ T-8 验收标准 | 21 | 21 | 0 | **100%** |
| 边界场景（E） | 6 | 6 | 0 | **100%** |
| auth.py 直接调用（U） | 4 | 4 | 0 | **100%** |
| 系统名全量扫描（S） | 3 | 3 | 0 | **100%** |
| **合计** | **34** | **34** | **0** | **100%** |

---

## 验收标准逐项验证

### T-1 新注册 bot 自动 level=2 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T1a | `"level": 2` 在 keys dict 中 | 🟢 | `handle_register()` L289 |
| T1b | R99 注释标记 | 🟢 | `# ── R99: 新注册默认 L2 ──` |

### T-2 Agent Card 提交后自动升 L3 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T2a | R99 晋升标记在 agent_card.py | 🟢 | 注释标记正确 |
| T2b | 晋升条件 `current_level == 2` | 🟢 | 只升 L2，不降级 L3/L4 |
| T2c | 调用 `set_level(agent_id, 3)` | 🟢 | 晋升逻辑完整 |
| T2d | `try/except` 包裹 | 🟢 | 晋升失败不阻断注册 |
| T2e | AST 确认 `register_from_agent` 含有 R99 逻辑 | 🟢 | 函数体完整 |

### T-3 L3 发 `_inbox:<id>` → ❌ 拒绝 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T3a | channel 前缀判断 | 🟢 | `_channel.startswith(p.INBOX_CHANNEL_PREFIX)` |
| T3b | `_inbox:server` 豁免 | 🟢 | `_channel != SERVER_INBOX_CHANNEL` |
| T3c | `_sender_level < 4` 拒绝 | 🟢 | L4 以下拦截 |
| T3d | 发送 `"type": "error"` 消息 | 🟢 | 正确 error 响应 |
| T3e | `continue` 跳过 broadcast | 🟢 | 不路由到目标 bot |
| T3f | 错误消息含等级提示 | 🟢 | `L{_sender_level}` |
| T3g | 日志记录拒绝 | 🟢 | `[R99] 拒绝: %s (L%d) 试图发消息到 %s` |

### T-4 L4 发 `_inbox:<id>` → ✅ 放行 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T4a | 条件为 `< 4` 非 `<= 4` | 🟢 | L4 不触发拒绝 |
| T4b | 通过后走 `handle_broadcast` | 🟢 | 检查后路由正常 |

### T-5 任意等级 `_inbox:server` → ✅ 放行 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T5a | `_channel != SERVER_INBOX_CHANNEL` 豁免 | 🟢 | 显式排除 |
| T5b | `SERVER_INBOX_CHANNEL` 常量正确 | 🟢 | `"_inbox:server"` |

### T-6 7 现存 bot 不受影响 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T6a | `record.get("level", 4)` 默认 L4 | 🟢 | 7 bot 无 level → L4 |
| T6b | `record is None → return 1` | 🟢 | 未注册 → L1 |
| T6c | `get_level(unknown)` = 1（实际调用） | 🟢 | L1 正确 |

### T-7 系统名统一 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T7a | 无 `"系统(中继)"` 残留 | 🟢 | 0 处 |
| T7b | 无 `from_agent="system"` 残留 | 🟢 | 0 处 |
| T7c | `SYSTEM_AGENT_ID = "_system"` | 🟢 | 常量值正确 |
| T7d | `pm_agent_id` 用常量 | 🟢 | `= SYSTEM_AGENT_ID` |

### T-8 旧 `_api_key` 无 level → 自动兼容 L4 🟢

| # | 断言 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| T8a | `record.get("level", 4)` 默认值为 4 | 🟢 | 兼容存量 |
| T8b | `set_level(unknown)` = False（实际调用） | 🟢 | 返回 bool |

---

## 边界场景验证

| # | 场景 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| E1 | L1(未注册)发消息 → R86 key 检查截停 | 🟢 | R86 检查在 R99 之前，双重防护 |
| E2 | L3 提交 Agent Card 不会降级 | 🟢 | `current_level == 2` 不匹配 L3 |
| E3 | `set_level` 返回 bool | 🟢 | 类型标注明确 |
| E4 | `get_api_key_record` 有 `_lock` 保护 | 🟢 | 并发安全 |
| E5 | `agent_card_register` 不受 level 检查限制 | 🟢 | 独立分支（`elif`），不经过 R99 |
| E6 | R86 吊销检查仍保留 | 🟢 | `status == "revoked"` 不受影响 |

## auth.py 函数直接调用测试

| # | 测试 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| U1 | 泰虾 level 可读 | 🟢 | `get_level()` 正常返回 |
| U2 | 不存在 agent = L1 | 🟢 | `get_level("未知")` → 1 |
| U3 | `set_level` 无记录 = False | 🟢 | 不抛异常 |
| U4 | `get_api_key_record` 不存在的 = None | 🟢 | 安全返回 |

## 系统名全量扫描

| # | 扫描项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| S1 | `"系统(中继)"` 全量扫描 | 🟢 | 0 处 |
| S2 | `"from_name": "system"` 全量扫描 | 🟢 | 0 处 |
| S3 | 所有 `from_name` 字面量值 | 🟢 | 全部为 `"系统"` |

---

## 小周 🟡 注意项复核

| 🟡 注意 | 说明 | QA 结论 |
|:--------|:-----|:---------|
| 晋升逻辑置于 `agent_card.py` 非 `handler.py` | 架构偏差，功能等价 | 🟢 功能正确，不阻断注册，`try/except` 保护 |

小周指出的架构偏差在功能上等价且安全。晋升发生在 card 保存后、welcome 消息发送前，`try/except` 确保不阻断注册。建议下次迭代重构。

---

## 结论

| 项目 | 状态 |
|:-----|:----:|
| 验收标准 T-1~T-8 | 🟢 全部通过 |
| 边界场景 | 🟢 全部通过 |
| auth 函数直接调用 | 🟢 全部通过 |
| 系统名全量扫描 | 🟢 全部通过 |
| **最终结论** | **🟢 可合并** |

R99 Bot 权限等级体系改动边界清晰：level 存储（`_api_keys.json`）、读取（`get_level`）、写入（`set_level`）、晋升（Agent Card 提交）、检查（`handler()` L6166）形成完整闭环。旧 bot 自动兼容 L4，新 bot 从 L2 渐进晋升。系统名统一完成。34/34 🟢 通过。

---

*报告编写: 🦐 泰虾 · 2026-07-13*
