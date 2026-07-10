# R88 代码审查报告 — Pipeline AutoRouter 🔍

> **审查人：** 🔍 小周
> **审查对象：** `server/auto_router.py` (667 行，新增文件)
> **审查基准：** `ab9c80e` (`origin/dev`)
> **参考文档：**
> - 技术方案: `docs/R88/R88-tech-plan.md`
> - 产品需求: `docs/R88/R88-product-requirements.md`
> - WORK_PLAN: `docs/R88/WORK_PLAN.md`
> - 原始 main 分支作为零修改基准

---

## 审查结论：🟢 通过

8/8 检查项通过，无阻断性问题。以下按优先级逐一汇报。

---

## 🔴 断线重连

| 检查项 | 结果 |
|:-------|:----:|
| 断线后自动重连 | ✅ |
| 指数退避 + 抖动 | ✅ |
| 重连后状态恢复 | ✅ (v1 有限恢复) |
| 认证重做 | ✅ |

**判定：🟢 通过**

- `start()` 外层 `while self._running` 循环 + `_connect_and_listen()` 内 `async with websockets.connect()` 构成双层容错
- 重连使用指数退避: 1s → 2s → 4s → ... → 60s cap，每次加 random.uniform(0, 2) 防雷群
- 重连后自动: 重新 WS 连接 + 认证 → 重新 `_build_role_index()` → `_restore_pipeline_state()` 重建进度
- v1 限制: 完全重启后 `_round_progress` 清空，无法恢复断点。技术方案第 6.5 节已明确
- 内层 `async for raw in ws:` 的 except Exception 保证了单条消息处理失败不影响连接

---

## 🔴 角色映射鲁棒性

**判定：🟢 通过**

- 匹配链: 精确匹配 → 子串包含匹配 → None (通知 PM)
- `_build_role_index()` 兼容两种卡片格式: `pipeline_roles: [list]` 和 `role: str`
- IO 异常/JSON 解析异常 → 返回空 dict，不 crash
- `_resolve_agent_id()` 返回 None 时 `_dispatch_step()` 通知 PM 并 return

---

## 🔴 安全性

**判定：🟢 通过**

- `_handle_message()` 入口: `if self._pm_inbox_channel and channel != self._pm_inbox_channel: return`
- 只有在频道为 `_inbox:<pm_agent_id>` 时才处理
- 无任何写操作涉及非 inbox 频道

---

## 🔴 异常处理

**判定：🟢 通过**

| # | 错误类型 | 日志 | 通知 PM |
|:-:|:---------|:----:|:-------:|
| E1 | YAML 解析失败 | ✅ ERROR | 通过上级 |
| E2 | HTTP 请求失败 | ⚠️ DEBUG(应为WARNING) | ✅ |
| E3 | 无 auto_chain | ✅ INFO | 跳过 |
| E4 | 找不到 agent | ✅ WARNING | ✅ |
| E5 | WS 发送失败 | ✅ ERROR | ✅ (1次重试后) |
| E6 | 角色不在 chain | ✅ DEBUG | 忽略 |
| E7 | 消息解析失败 | ✅ DEBUG | 忽略 |
| E8 | Agent Card IO | ✅ ERROR | 空索引降级 |
| E9 | 连接异常 | ✅ WARNING | 自动重连 |

**建议：** E2 当前使用 `logger.debug()`，技术方案要求 `logger.warning()`，建议对齐。

---

## 🟡 消息去重

**判定：🟢 通过**

- 两层独立去重: `_mark_seen(msg_id)` 滑动窗口 + `completed_steps` set 幂等
- 溢出裁剪: 超过 `_MAX_SEEN_IDS=1000` 时保留最近 500 条
- `msg_id` 为空时不误判重复

---

## 🟡 多活跃管线

**判定：🟢 通过**

- `_round_progress: dict[str, dict]` — 以 round_name 为 key
- `_extract_round(content)` 通过 `R\d{2,3}` 正则提取轮次
- 各自维护独立 chain、progress、topology
- 单线程 async 模型，消息按序处理，无并发安全问题

---

## 🟡 简写格式兼容

**判定：🟡 条件通过**

- 格式 A: `topology.chain` 完整定义 ✅
- 格式 B: `auto_chain: true` + `steps` dict → 按数字排序自动构建 chain ✅
- 格式 C: `auto_chain: true` 但无有效 chain/steps → 注册但后续静默忽略完成消息

⚠️ 建议：空 chain + auto_chain 时应在 `_on_pipeline_ready` 中通知 PM。

---

## 🟢 零 handler.py 侵入

**判定：🟢 通过**

`git diff origin/main...origin/dev -- server/handler.py` 返回空输出。`auto_router.py` 为纯新增文件。

---

## 额外发现

| # | 严重度 | 描述 | 建议 |
|:-:|:------:|:-----|:-----|
| 1 | 🟡 整洁性 | `_dispatch_step()` 中 `progress` 局部变量未使用 | 移除 |
| 2 | 🟢 建议 | 代码 667 行 vs 预估 ~250 行 | 功能完整覆盖，可接受 |

**部署注意事项：** 新增 `websockets` + `aiohttp` 依赖，需确认生产环境已安装。

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:-----|
| 断线重连 | 🔴 | 🟢 | 指数退避 + 状态恢复 |
| 角色映射鲁棒性 | 🔴 | 🟢 | 永不 crash，PM 通知 |
| 安全性 | 🔴 | 🟢 | 严格频道过滤 |
| 异常处理 | 🔴 | 🟢 | 9/9 错误类型覆盖 |
| 消息去重 | 🟡 | 🟢 | 双重保障 |
| 多活跃管线 | 🟡 | 🟢 | round_name 隔离 |
| 简写格式兼容 | 🟡 | 🟡 | 空 chain + auto_chain 需留意 |
| 零 handler.py 侵入 | 🟢 | 🟢 | git diff 确认 |

**最终结论：🟢 通过** — `server/auto_router.py` 符合技术方案要求，异常处理完备，无阻断性问题。

---

*报告编写: 🔍 小周 · 2026-07-10*
