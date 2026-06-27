# R43 代码审查报告

> **版本：** v1.0
> **审查角色：** 🔍 review-bot
> **日期：** 2026-06-27
> **审查范围：** `312b3ab` — A/B/C/D 四方向实现
> **审查文件：** `server/config.py` + `server/handler.py`

---

## 审查结论

🟢 **通过** — 可进入 Step 5 测试验证

---

## 改动统计

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/config.py` | `PIPELINE_STEP_MAP` 扩展 `timeout_hours`/`escalation` 字段 | +12/-6 |
| `server/handler.py` | 全局状态 + 看门狗函数群 + `_cmd_step_complete` 增强 + 惰性启动入口 | +163 |
| **合计** | | **+175 / -0** |

---

## 方向审查

### A 看门狗定时器 🟢 通过

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 惰性启动 | ✅ | `_ensure_watchdog()` 在 `handle_broadcast` 入口首次调用时创建协程 |
| 10min 扫描周期 | ✅ | `_watchdog_loop()` 中 `asyncio.sleep(600)` |
| 活跃管线扫描 | ✅ | `_watchdog_scan()` 遍历 `_PIPELINE_STATE`，跳过非 active 管线 |
| 超时判断逻辑 | ✅ | 计算 `now - started_at` 与 `timeout_hours` 比较 |
| 重复告警防范 | ✅ | `_watchdog_alerts{round/step: ts}` 字典，30min 冷却判断 |
| 优雅退出 | ✅ | `_watchdog_loop()` try/except `CancelledError` 日志记录 |
| 零管线零输出 | ✅ | `_watchdog_scan()` 空 `_PIPELINE_STATE` 直接 return |

#### 发现

| # | 文件 | 行号 | 严重度 | 说明 |
|:-:|:-----|:----:|:------:|:------|
| A-2 | `handler.py` | `_ensure_watchdog()` ~L922 | 🟢 P3 | `_watchdog_task` 在 `_watchdog_started` 置位前赋值，存在极小竞态窗口（实际无害） |

### B 超时配置 🟢 通过

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 字段扩展 | ✅ | 6 步全加 `timeout_hours`(float) 和 `escalation`(str) |
| 默认值回退 | ✅ | `_get_step_timeout()`: config→`_STEP_TIMEOUT_DEFAULTS`→`inf` |
| env 覆盖 | ✅ | `PIPELINE_STEP_MAP_OVERRIDE` JSON 原地 update，字段级合并 |
| 6 步结构 | ✅ | step1~step6 与 WORK_PLAN 对齐，无 step1+2 合并残迹 |
| 数据类型 | ✅ | `timeout_hours` 使用 float，`escalation` 使用 str |

### C 超时升级通知 🟡 有条件通过

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 首次告警 | ✅ | `_check_watchdog_alert()` 返回 `"first"` → `_send_watchdog_alert()` |
| 30min 重复 | ✅ | `_watchdog_alerts` 冷却判断 `WATCHDOG_REALERT_INTERVAL=1800` |
| 解除通知 | ✅ | `_cmd_step_complete` 中 `_clear_watchdog_alert()` + `_send_clear_alert()` |
| 纯文本格式 | ✅ | 消息中无 Markdown 代码块 |
| `_admin` 频道 | ✅ | `_persist_broadcast(p.ADMIN_CHANNEL, ...)` |
| 告警信息完整 | ✅ | 含管线名、Step 名&编号、角色、挂起时间、阈值、启动时间、建议 |

#### 发现

| # | 文件 | 行号 | 严重度 | 说明 |
|:-:|:-----|:----:|:------:|:------|
| C-1 | `handler.py` | `_watchdog_scan()` ~L966 | 🟢 P3 | 死分支：`_check_watchdog_alert()` 返回 `None` 而非 `"cooldown"`，`if alert_type == "cooldown"` 分支永不执行。不影响逻辑 |

### D 交接响应增强 🟢 通过

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 角色名解析 | ✅ | 从 `auth.get_users()` + 工作室成员匹配角色 |
| 返回值增强 | ✅ | 追加「已点名 {role_display}，等待确认」和「负责人请切到工作室频道」 |
| 向后兼容 | ✅ | 仅在交接 Step 时附加新行，旧调用不受影响 |

### 向后兼容 🟢 通过

| 场景 | 兼容性 | 说明 |
|:-----|:------:|:------|
| 无活跃管线 | ✅ | 看门狗直接 return，零输出 |
| 旧配置无 timeout_hours | ✅ | `_get_step_timeout()` 回退默认值 |
| 旧 PIPELINE_STEP_MAP_OVERRIDE | ✅ | JSON update 字段级合并 |
| R42 管线命令 | ✅ | 接口不变，返回值仅增强 |
| 人工接力流程 | ✅ | 看门狗不干涉 |
| 服务重启 | ✅ | 告警状态重置，重启后 10min 内重新检测 |

---

## 问题清单

| # | 文件 | 行号 | 严重度 | 状态 | 说明 |
|:-:|:-----|:----:|:------:|:----:|:------|
| C-1 | `handler.py` | `_watchdog_scan()` L966 | 🟢 P3 | **建议修复** | 死分支 `"cooldown"` — `_check_watchdog_alert()` 从不返回此值 |
| A-2 | `handler.py` | `_ensure_watchdog()` L922 | 🟢 P3 | **无需修复** | 极小竞态窗口，实际无害 |

---

## 最终结论

> **审查结论：🟢 通过**
>
> 两项发现均为 P3 非阻塞问题。建议 C-1 死分支清理可在后续维护中处理，不影响当前 Step 5 测试验证推进。
>
> — 🔍 review-bot
