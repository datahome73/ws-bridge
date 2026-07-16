# R122 代码审查报告 — 管线超时告警 + PM 手动推进

> **审查人：** 🔍 小周
> **基线：** `origin/dev`（commit `b226203`）
> **审查范围：** R122 Step 3 编码（4 个关联 commit: 91abebc d1a9186 9d2bdae 33b4cfc）
> **参考文档：** [需求文档](./R122-product-requirements.md)，[技术方案](./R122-tech-plan.md)，[开发计划](./WORK_PLAN.md)
> **结论：** ⚠️ **有条件通过 — 1 Warning, 1 Suggestion**

---

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| A-1 | `in_progress` 的 step 写入 `dispatched_at` | step 字典含 `dispatched_at: float` + `timeout_alerted: false` | ✅ | `main.py:2870-2871` |
| A-2 | 超时扫描协程每 5 分钟正常运行 | 启动日志 + 无阻塞 | ✅ | `asyncio.create_task` 非阻塞 |
| A-3 | step 正常完成时不触发告警 | 跳过 `done` 状态 step | ✅ | `if status != 'in_progress': continue` |
| A-4 | step 超时后 PM 收到告警 | `⏰ 管线超时告警` | ✅ | `_send_to_agent(pm_id, ...)` |
| A-5 | 同一 step 不再重复告警 | `timeout_alerted=True` 持久化 | ✅ | 告警后设置 + `mgr.save()` |
| A-6 | 无超时的管线扫描无副作用 | 正常跳过 | ✅ | `if elapsed < threshold: continue` |

**新增功能（超出原始需求范围）：**

| # | 验收项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| B-1 | `##advance##R{N}##step=N` 推进管线 | ✅ | 构造 `已完成` 消息调 `_try_advance_pipeline()` |
| B-2 | 推进成功/失败均有反馈 | ✅ | 成功/失败均返回状态消息 |

---

## 二、文件改动总览

### 2.1 核心实现 commit: `91abebc`

| # | 文件 | 动作 | 行数 | 说明 |
|:-:|:-----|:----:|:----:|:-----|
| 1 | `server/common/config.py` | 修改 | **+7 -1** | `PIPELINE_TIMEOUT_ALERT_MINUTES`（30min）+ `PIPELINE_TIMEOUT_SCAN_INTERVAL`（300s） |
| 2 | `server/ws_server/main.py` | 修改 | **+101** | 超时扫描基础设施（3 函数 + 启动接线 + dispatched_at） |

### 2.2 状态变量迁移: `d1a9186` + `9d2bdae`

| # | 文件 | 动作 | 行数 | 说明 |
|:-:|:-----|:----:|:----:|:-----|
| 3 | `server/ws_server/state.py` | 修改 | **+4** | `_TIMEOUT_SCAN_TASK` + `_TIMEOUT_SCAN_STARTED` |
| 4 | `server/ws_server/main.py` | 修改 | **-2** | 模块级变量 → `state.*` |

### 2.3 PM 手动推进: `33b4cfc`

| # | 文件 | 动作 | 行数 | 说明 |
|:-:|:-----|:----:|:----:|:-----|
| 5 | `server/ws_server/main.py` | 修改 | **+48 -1** | `_handle_hash_advance()` + 帮助文本 |

**总计：** 3 文件，**+158 -4 行**

---

## 三、发现项

### 🔴 Critical: 无

### 🟡 Warning 1: `##advance##` 无权限校验

**位置：** `_handle_hash_advance()`（33b4cfc）

**问题：** `##advance##R{N}##step=N` 无角色检查，任何 agent 可推进任何管线。跳过 step 可能绕过测试/审查/部署。帮助写 "PM使用" 但无防御。

**建议：** 仅允许 `config.PIPELINE_PM_AGENT_ID` 调用：

```python
if agent_id != config.PIPELINE_PM_AGENT_ID:
    return await _send_error(ws, agent_id, "权限不足: 仅 PM 可用 ##advance##")
```

### 💡 Suggestion 1: 告警时间戳统一使用 `now`

`_pipeline_timeout_scan()` 开头已 `now = time.time()`，payload 又调一次。建议统一。

### 💡 Suggestion 2: 告警内容添加 `step_title`

包含 `step.get('title', '')` 让 PM 一眼看出是哪环节超时。

---

## 四、功能完整性验证

### 4.1 边界情况覆盖

| 场景 | 处理 | 结果 |
|:-----|:-----|:----:|
| `TIMEOUT_ALERT_MINUTES=0` | 不启动扫描 | ✅ |
| 旧 JSON 无 `dispatched_at` | `if not dispatched_at: continue` | ✅ |
| 旧 JSON 无 `timeout_alerted` | `get()` 返回 None → 触发一次 | ✅ 重启后合理 |
| 告警发送失败 | `except` 捕获 | ✅ |
| 多管线超时 | 单协程顺序遍历 | ✅ |
| `step=` 非法参数 | `isdigit()` 校验 | ✅ |

### 4.2 回归风险

| 修改 | 风险 |
|:-----|:----:|
| config.py 新增配置 | 🟢 |
| `_auto_dispatch()` 追加 2 行 | 🟢 |
| 扫描协程 | 🟢 |
| state.py 新增变量 | 🟢 |
| `_handle_hash_advance()` | 🟡 |

---

## 五、汇总 & 结论

### 亮点

- 三层防护：start → scan → alert 职责清晰
- 持久化完备：`dispatched_at` / `timeout_alerted` 均写入 JSON
- 向后兼容旧 JSON 无 `dispatched_at` 时优雅跳过
- 状态变量迁移按项目约定完成

### 结论

> ⚠️ **有条件通过。** 超时告警核心功能完整、防御充分。**`##advance##` 需添加 PM 权限校验后方可合并。**

### 建议顺序

1. **🟡 必修复：** `_handle_hash_advance()` PM 权限校验
2. 💡 可选：统一告警时间戳
3. 💡 可选：告警内容加 `step_title`

---

**审查日期：** 2026-07-16
**审查人：** 🔍 小周
