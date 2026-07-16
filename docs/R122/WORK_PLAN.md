# R122 开发计划（WORK_PLAN）

> **仓库：** `datahome73/ws-bridge`
> **状态：** ✅ 项目负责人审核通过

---

## 范围

仅实现需求 A（需求 B/C 搁置）：
- **管线超时告警：** Step 派活后 30 分钟无回复 → 自动通知 PM（小谷），每 step 只发一次

## 变更文件

| 文件 | 改动类型 | 说明 |
|:-----|:--------|:------|
| `server/common/config.py` | +8 行 | 新增 `PIPELINE_TIMEOUT_ALERT_MINUTES` 和扫描间隔配置 |
| `server/ws_server/main.py` | ~60 行 | `_auto_dispatch` 记录派活时间 + 新增超时扫描循环 + 启动接线 |

## 验收检查表

| # | 验收项 | 优先级 |
|:-:|:------|:-----:|
| A-1 | `in_progress` 的 step 写入 `dispatched_at` 时间戳 | P0 🟢 |
| A-2 | 超时扫描协程每 5 分钟正常运行，不阻塞主循环 | P0 🟢 |
| A-3 | step 正常完成时不触发告警 | P0 🟢 |
| A-4 | step 超时 30 分钟后 PM 收到告警，内容含轮次和停滞步骤 | P0 🟢 |
| A-5 | 同一 step 不再重复告警（`timeout_alerted=True`） | P0 🟢 |
| A-6 | 无超时的管线扫描不产生任何副作用（不误告警） | P1 🟡 |
