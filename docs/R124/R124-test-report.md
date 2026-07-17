# R124 Step 5 — 🧪 测试验证报告

> **测试人：** 🦐 泰虾（QA）
> **测试依据：** `docs/R124/R124-product-requirements.md` v1.0
> **测试范围：** server/ws_server/main.py (+529/-32), server/common/config.py (+2), gateway-plugin/__init__.py (+26)
> **测试 Commits：** 856a6ed + a2a7dfe + b9c19c3 (HEAD: 407661f)
> **测试模式：** 源码级分析（静态验证）
> **测试日期：** 2026-07-17

---

## 测试结论

**38/41 项通过 ✅ | 3 项失败 ❌**

**状态：🔴 不通过 — 3 项失败（含 2 个预存 Critical + 1 个新发现 Bug）**

---

## 🔴 F-1（Critical）— 代码重复（预存，Step 4 未修复）

| 函数 | 出现位置 | 说明 |
|:-----|:--------|:-----|
| _handle_reject | L2950 + **L3498** | 简易版（缺 PS.COMPLETED + stuck 守卫）→ 被覆盖 |
| _archive_pipeline | L2999 + **L3838** | 旧版含 `_notify_pm`，**新版无**（→ 新 Bug） |

**新发现：** 活跃版本（L3838）缺少 `_notify_pm` 调用，归档后 PM 收不到通知。

---

## 🔴 F-2（Critical）— ##help 缺失 ##archive（预存，Step 4 未修复）

两个帮助块（L3688-3693 和 L3726-3731）均缺少 `##archive` 说明。

```diff
+ "`##archive##R{N}` — 归档管线（PM使用）\n"
```

路由已注册（L3717），仅显示层缺失。

---

## ✅ 功能验证通过项

### A 驳回自动再派活 — 10/10 ✅

| # | 验收项 | 状态 | 证据 |
|:-:|:-------|:----:|:-----|
| A-1 | Step4退回 -> step3~4 status重置pending, output清空 | ✅ | ctx.steps[i]["status"]="pending" + output=None |
| A-2 | 退回原因写入 ctx.steps[2][reject_reason] | ✅ | reject_reason 持久化到 rollback_start step |
| A-3 | 退回后仅回退状态，不自动重新派活 | ✅ | reject handler 内无 auto_dispatch |
| A-4 | PM 收到退回通知（含原因 + 管线状态） | ✅ | _notify_pm(ctx, rejected_step, "rejected", ...) |
| A-5 | 累计退回 3 次后第 4 次 stuck | ✅ | reject_count>=4 -> ctx.status="stuck" |
| A-6 | 无分隔符 -> 前 100 字符 | ✅ | reject_reason = content[:100] |
| A-7 | PM 可自行决定后续动作 | ✅ | 通知含「未自动派活」指引 |
| A-8 | Rollback: Step1/2->index1, Step3+->index2 | ✅ | rollback_start = 1 if <=2 else 2 |
| A-9 | relay 触发 _handle_reject | ✅ | ensure_future(_handle_reject(...)) |
| A-10 | 终端状态守卫(completed/stuck) | ✅ | PS.COMPLETED + stuck 检查 |

### B 管线自动归档 — 7/8 ✅ (1 新 Bug)

| # | 验收项 | 状态 | 证据 |
|:-:|:-------|:----:|:-----|
| B-1 | 全 step done 后自动归档 | ✅ | ensure_future(_archive_pipeline(round_name)) |
| B-2 | 归档写入 pipeline_archive.json | ✅ | Path(config.DATA_DIR) / "pipeline_archive.json" |
| B-3 | 归档含完整 steps/artifacts/references/summary | ✅ | 字典含全部字段 |
| B-4 | ##archive##R{N} 手动归档 | ✅ | _handle_hash_archive + PM 权限 |
| B-5 | ##status 归档后可查 | ✅ | _find_archive 路径 |
| B-6 | mgr._contexts pop 移除 | ✅ | pop(round_name, None) |
| B-7 | >50 条 trim 到 30 | ✅ | MAX_ARCHIVE_TRIM=50, KEEP_ARCHIVE=30 |
| **B-8** | **归档后 PM 收到通知** | **❌** | **活跃版(L3838)缺 _notify_pm** |

### C Step 产出基本验证 — 8/8 ✅

| # | 验收项 | 状态 | 证据 |
|:-:|:-------|:----:|:-----|
| C-1 | sha=abc1234 -> valid_format | ✅ | re.match(r"^[0-9a-f]{7,40}$") |
| C-2 | sha=abc（7位）合法 | ✅ | 正则 {7,40} 允许 |
| C-3 | sha=not-a-sha! -> invalid_format | ✅ | 正则不匹配 |
| C-4 | 无 sha 不设字段 | ✅ | if _sha_v: 守卫 |
| C-5 | 不阻断管线推进 | ✅ | 无 return，仅标记 |
| C-6 | PIPELINE_OUTPUT_VERIFICATION 控制 | ✅ | env var guards git check |
| C-7 | _verify_sha_remote 存在 | ✅ | async def 定义 |
| C-8 | 5s 超时 | ✅ | async with asyncio.timeout(5) |

### D 超时自动化处理 — 8/8 ✅

| # | 验收项 | 状态 | 证据 |
|:-:|:-------|:----:|:-----|
| D-1 | 30min 重发派活(re_notified) | ✅ | re_notified 标志 + _auto_re_notify |
| D-2 | PM 收到重发通知 | ✅ | 「已重新发送」PM 通知 |
| D-3 | 45min timeout 标记 | ✅ | step["status"]="timeout" |
| D-4 | _auto_re_notify 完整实现 | ✅ | 模板渲染 + 重发标记 + 日志 |
| D-5 | 原有 30min 告警保留 | ✅ | timeout_alerted 保留 |
| D-6 | 阶梯顺序:告警->重发->标记 | ✅ | 3 独立 if 块互锁 |
| D-7 | 配置参数: RETRY_MINUTES | ✅ | getattr(config, ..., 30) |
| D-8 | 配置参数: MARK_MINUTES | ✅ | getattr(config, ..., 45) |

---

## 🟡 改进建议

| # | 建议 | 优先级 |
|:-:|:-----|:------|
| W-1 | 删除 L2950-L3068 死代码区间（旧版 _handle_reject + _archive_pipeline）| P0 |
| W-2 | 两个 ##help 块补上 ##archive 说明 | P0 |
| W-3 | 活跃 _archive_pipeline（L3838）补加 _notify_pm 调用 | P0 |
| W-4 | _fmt_ts 辅助函数后续整理 | P2 |

---

## 修复建议时间线

```
P0 Critical - F-1 删除死代码(L2950-L3068)      Dev 5min
P0 Critical - F-2 ##help 补 ##archive            Dev 2min
P0 Bug      - B-8 _archive_pipeline补 _notify_pm Dev 1min
```

> **测试结论：** 🔴 不通过 — 3 项失败
> **修复后重测：** 由 PM 决定重新派活 Dev 或人工确认
