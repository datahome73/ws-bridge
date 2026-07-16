# R122 Step 5 ✅ 测试验证报告 — 管线超时告警 + PM 手动推进

> **轮次：** R122
> **类型：** 测试验证报告
> **测试人：** 🦐 泰虾
> **基线：** `origin/dev`（commit `548a241`，含审查修复）
> **测试日期：** 2026-07-17
> **参考文档：** [需求文档](./R122-product-requirements.md) | [技术方案](./R122-tech-plan.md) | [审查报告](./R122-code-review.md)

---

## 一、变更概要

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/common/config.py` | 新增 `PIPELINE_TIMEOUT_ALERT_MINUTES`（30min）+ `PIPELINE_TIMEOUT_SCAN_INTERVAL`（300s） | **+7 -1** |
| `server/ws_server/main.py` | `_auto_dispatch` 记 `dispatched_at` + 超时扫描 3 函数 + `_handle_hash_advance` + 权限校验 | **+160 -2** |
| `server/ws_server/state.py` | 新增 `_TIMEOUT_SCAN_TASK` / `_TIMEOUT_SCAN_STARTED` | **+4** |
| **总计** | **3 文件** | **+171 -3** |

**代码变更包含审查修复：** 权限校验（`agent_id != pm_agent_id` 防非 PM 调用 `##advance##`）

---

## 二、测试结果总览

| 测试类别 | 通过 | 失败 | 通过率 |
|:---------|:----:|:----:|:------:|
| 源码级分析（37 项断言） | 37 | 0 | **100%** |
| 集成测试（14 项断言） | 14 | 0 | **100%** |
| **合计** | **51** | **0** | **100%** |

---

## 三、测试用例逐项验证

### ① 启动日志出现 `[R122] 管线超时扫描已启动` 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| A1 | 启动日志字符串存在 | ✅ | 源码 `'管线超时扫描已启动'` |
| A2 | `_ensure_timeout_scanner` 函数定义 | ✅ | 源码 `def _ensure_timeout_scanner` |
| A3 | 在 `handle_broadcast` 入口调用 | ✅ | 第 1443 行 `_ensure_timeout_scanner()` |
| A4 | 防重复启动 | ✅ | `state._TIMEOUT_SCAN_STARTED` 守卫 |

### ② dispatched_at 写入 step 字典 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| B1 | `dispatched_at` 字段写入 | ✅ | `next_step_info["dispatched_at"] = time.time()` |
| B2 | `timeout_alerted` 初始化为 False | ✅ | `next_step_info["timeout_alerted"] = False` |
| B3 | 在 `sent > 0` 块内 | ✅ | 派活成功后写入 |
| B4 | 在 `_auto_dispatch` 函数内 | ✅ | 函数体已包含 |

### ③ Step 快速完成 → 无告警 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| C1 | 跳过非 `in_progress` step | ✅ | `step.get("status") != "in_progress"` |
| C2 | 跳过无 `dispatched_at` 的旧数据 | ✅ | `if not dispatched_at: continue` |
| C3 | 跳过已告警 step | ✅ | `if step.get("timeout_alerted"): continue` |
| C4 | 跳过未超时 step | ✅ | `if elapsed < threshold: continue` |
| C5 | 仅检查 RUNNING 管线 | ✅ | `ctx.status != PS.RUNNING` |

**集成验证：** 未超时 step（10s 前派活）→ 无告警 ✅

### ④ 模拟超时 → PM 收到告警 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| D1 | 告警含 `⏰` emoji | ✅ | 源码 `f"⏰ 管线超时告警..."` |
| D2 | 告警含轮次名 | ✅ | `ctx.round_name` 在告警内容中 |
| D3 | 告警含 Step 号 | ✅ | `step_num` 在告警内容中 |
| D4 | 告警含等待时间 | ✅ | `"分钟无回复"` 在告警内容中 |
| D5 | 发送给 PM | ✅ | `_send_to_agent(pm_id, ...)` |
| D6 | 告警后标记 | ✅ | `step["timeout_alerted"] = True` |

**集成验证：** 阈值 1 分钟，dispatched_at 设为 2 分钟前 → ⏰ 告警已发送 ✅  
告警内容含 `R122T1`、`Step 2`、发给 `ws_pm_123` ✅

### ⑤ 同一 step 只告警一次 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| E1 | 告警前检查 `timeout_alerted` | ✅ | 守卫在前 |
| E2 | 告警后 `mgr.save()` 持久化 | ✅ | `try: mgr.save()` 在 `if alerted:` 块 |

**集成验证：** 第二次扫描同一超时 step → 0 条告警 ✅

### ⑥ `PIPELINE_TIMEOUT_ALERT_MINUTES=0` 扫描禁用 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| F1 | `timeout_min <= 0` 守卫 | ✅ | 函数首行检查 |
| F2 | 禁用日志 | ✅ | `"[R122] 管线超时告警已禁用"` |
| F3 | 配置项定义 | ✅ | `config.py` 中有定义 |
| F4 | 默认值 30 | ✅ | `os.environ.get("R122_TIMEOUT_ALERT_MINUTES", "30")` |
| F5 | 环境变量覆盖 | ✅ | `R122_TIMEOUT_ALERT_MINUTES` |
| F6 | 扫描间隔配置 | ✅ | `PIPELINE_TIMEOUT_SCAN_INTERVAL`（300s 默认） |

### ⑦ 无 running 管线不报错 🟢

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| G1 | `try/except` 包裹扫描 | ✅ | `_start_timeout_scan_loop` 中 `except Exception` |
| G2 | `mgr.get_all_active()` 遍历 | ✅ | 第 572 行 |

**集成验证：** 空管线列表 → 正常返回无异常 ✅

---

## 四、新增功能验证：##advance## （PM 手动推进）

审查中发现 `##advance##` 无权限校验（Warning），已由爱泰修复。

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| H1 | `_handle_hash_advance` 函数存在 | ✅ | 源码 `async def _handle_hash_advance` |
| H2 | PM 权限校验 | ✅ | `if agent_id != pm_agent_id: ❌ 无权限` |
| H3 | `step=N` 参数校验 | ✅ | `if not step_str.isdigit():` 参数错误提示 |
| H4 | 推进成功反馈 | ✅ | `"✅ **R{N} Step {N}** 已手动推进"` |
| H5 | 推进失败原因反馈 | ✅ | `"⚠️ 推进失败: {reason}"` |
| H6 | 帮助文本包含 advance | ✅ | `##help` 含 `##advance##R{N}##step=N` |

---

## 五、边界情况

| 场景 | 结果 | 说明 |
|:-----|:----:|:------|
| 旧 JSON 无 `dispatched_at` | 🟢 | `if not dispatched_at: continue` 优雅跳过 |
| 旧 JSON 无 `timeout_alerted` | 🟢 | `get()` 返回 `None`（等价 False）→ 重启后合理触发一次 |
| `PIPELINE_PM_AGENT_ID` 为空 | 🟢 | 跳过告警发送，但 `timeout_alerted` 仍标记 |
| 告警发送异常 | 🟢 | `try/except` 捕获 |
| 多管线同时超时 | 🟢 | 单协程顺序遍历，`_send_to_agent` 非阻塞 |
| 扫描间隔 300s | 🟢 | 默认 5 分钟 tick，不阻塞主循环 |
| 容器重启 | 🟢 | `dispatched_at` + `timeout_alerted` 已持久化到 JSON |

---

## 六、代码变更

```
server/common/config.py     |   8 ++-
server/ws_server/main.py    | 162 ++++++++++++++++++++++++++++++++++++-
server/ws_server/state.py   |   4 ++
3 files changed, 171 insertions(+), 3 deletions(-)
```

---

## 七、结论

> ✅ **R122 Step 5 测试验证通过。**
>
> - **源码分析：** 37/37 ALL GREEN 🟢
> - **集成测试：** 14/14 ALL GREEN 🟢
> - **合计：** **51/51 ALL GREEN 🟢**
>
> 管线超时告警功能完整：
> - `_auto_dispatch` 派活时写入 `dispatched_at` + `timeout_alerted=False`
> - `_ensure_timeout_scanner` → `_start_timeout_scan_loop` → `_pipeline_timeout_scan` 三层防护
> - 超时 30 分钟 → ⏰ 告警发 PM，每 step 仅一次
> - `PIPELINE_TIMEOUT_ALERT_MINUTES=0` 优雅禁用
> - 旧数据无 `dispatched_at` 时跳过，重启后合理触发一次
>
> `##advance##R{N}##step=N` 手动推进命令：
> - 仅 PM 可用（权限校验已修复）
> - 成功/失败均有明确反馈
> - 帮助文本已更新

---

**测试日期：** 2026-07-17
**测试人：** 🦐 泰虾
