# R143 需求文档 — 跨步状态同步修复轮

> **来源文档：** `docs/research/L4-auto-pipeline-manager-needs-research.md`
> **轮次：** R143
> **类型：** 🛠️ 跨步状态同步修复轮（`##advance` 跳步时遗漏 `in_progress` 状态中间步）
> **版本：** v1.0
> **日期：** 2026-07-23
> **基于：** `a78d63b`（R142 已完成 — 32/32 ALL GREEN 🟢）
> **状态：** 📝 初稿

---

## §0 本轮定位

仅 1 项改动：修复 `##advance` 跨步推进时状态不同步的 bug。

| # | 问题 | 严重度 | 影响 | 改动量 |
|:-:|:-----|:------:|:-----|:------:|
| 1 | **`##advance` 跨步时只跳过 `pending` 步，遗漏 `in_progress` 步**，造成超时假报警 | 🔴 P1 | 每次手工推进后必出现 | 改 1 个条件 + 2 行清理 |

**排除项（核实后认为不需要改）：**
- **B-5 重复派活**：其他 bot 收到重复派活会静默忽略（已完成就不重复处理），仅 Web 端人类看着不舒服。不是功能性 bug，降级为 P3，不占用本轮。
- **R-1 超时提醒去噪**：根因是跨步不同步导致的假报警，修复跨步同步后自然消失，无需额外改动。

---

## §1 问题与方案

### 1.1 `##advance` 跨步状态同步修复（P1）

**问题：** 手工用 `##advance##R{N}##step=N` 跳步推进后，中间状态为 `in_progress` 的步骤不同步为 `skipped`，超时扫描器仍认为该步在运行中，触发假报警。

#### 场景重现

```
管线当前在 Step 2：已派活给小开，小开完成了但没发完成消息（status=in_progress）
经理手工推进：##advance##R143##step=4

当前 _handle_hash_advance 的实际行为（L1293-1303）：
┌──────────┬─────────────┬────────────────────────────────┐
│ Step     │ 原来的状态  │ 跳步后的状态                    │
├──────────┼─────────────┼────────────────────────────────┤
│ Step 1   │ pending     │ → skipped ✅ （条件命中）       │
│ Step 2   │ in_progress │ → ❌ 不动！！（条件不命中！）  │  ← bug!
│ Step 3   │ pending     │ → skipped ✅                   │
│ Step 4   │ pending     │ → in_progress ✅               │
└──────────┴─────────────┴────────────────────────────────┘

30分钟后，超时扫描器发现 Step 2：
  - status = in_progress（还在！）
  - dispatched_at = 30+ 分钟前
→ 发超时告警「Step 2 已超时 30 分钟」→ 假报警
  实际上管线已经在 Step 4 了
```

#### 根因

`_handle_hash_advance` 第 1296 行条件太窄：

```python
if step_num_i < step_num and s.get("status") in ("pending",):
```

只检查 `pending` 一种状态。`in_progress`、`failed` 等其他状态不会处理，导致遗留。

#### 改动方案

改 1 个条件 + 清理 `dispatched_at`：

```python
# ── R143 修复 ──
if step_num_i < step_num and s.get("status") not in ("done",):
    s["status"] = "skipped"
    s.pop("dispatched_at", None)  # 清除时间戳，避免超时扫描器误判
    logger.info("[R143] %s step%d → skipped（##advance 跨步，原状态=%s）",
                round_name, step_num_i, old_status)
# ─────────────────
```

**语义变化：**

| 条件 | 跳过范围 | 问题 |
|:-----|:---------|:-----|
| 旧：`in ("pending",)` | 仅 pending | ❌ in_progress 遗漏 |
| 新：`not in ("done",)` | 所有未完成的步 | ✅ 包含 in_progress/failed/pending |

**修复后行为：**

```
##advance##R143##step=4：
┌──────────┬─────────────┬──────────────────────────────────┐
│ Step     │ 原状态      │ 跳步后                           │
├──────────┼─────────────┼──────────────────────────────────┤
│ Step 1   │ pending     │ → skipped                        │
│ Step 2   │ in_progress │ → skipped + dispatched_at 清除   │  ✓ 修复
│ Step 3   │ pending     │ → skipped                        │
│ Step 4   │ pending     │ → in_progress ✅                 │
└──────────┴─────────────┴──────────────────────────────────┘
```

#### 改动量

| 文件 | 改动 | 行数 | 风险 |
|:----|:-----|:----:|:----:|
| `server/ws_server/pipeline_engine.py` | `_handle_hash_advance` 跨步条件 + dispatched_at 清理 | +3/-1 | 🟢 |

#### 验证方法

```
# 测试用例（源码审核级）：
1. 创建管线，派活 Step 2（status → in_progress）
2. 执行 ##advance##R143##step=4
3. 检查 Step 2 status == "skipped"
4. 检查 Step 2 无 dispatched_at 字段
5. 超时扫描器不因 Step 2 触发
```

#### 验收标准

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| AS-1 | `##advance` 跳步后 `in_progress` 的中间步 → `skipped` | 功能 | P1 |
| AS-2 | `##advance` 跳步后 `done` 的中间步 → 保持 `done`（不降级） | 回归 | P1 |
| AS-3 | 被跳过的 step 清除 `dispatched_at` 字段 | 功能 | P1 |
| AS-4 | 目标 step（跳到的步）保持 `in_progress` | 回归 | P1 |
| AS-5 | `pending` 的中间步 → `skipped`（与修复前行为一致） | 回归 | P1 |
| AS-6 | 修复后 `in_progress` 中间步不触发超时扫描 | 验证 | P1 |

---

## §2 TODO.md 更新

| # | 事项 | 旧状态 | 新状态 |
|:-:|:-----|:------:|:------:|
| B-3 | status_icons in_progress 缺失 | ⬜ 待修复 | 🟢 **已修复（R142）** |
| B-4 | 完成消息格式容错 | ⬜ 待修复 | 🟢 **已修复（R142）** |
| B-5 | R141 重复派活 | ⬜ 待排查 | 🟢 **降级 P3（bot 静默忽略，仅 Web 端视觉问题）** |
| R-1 | Step 超时提醒噪音 | ⬜ 待排期 | 🟢 **根因已修复（跨步同步 `in_progress`）** |

---

## §3 变更记录

| 日期 | 版本 | 变更 |
|:----|:----:|:-----|
| 2026-07-23 | v1.0 | 初版 — 跨步状态同步修复（`##advance` 遗漏 `in_progress` 中间步） |
