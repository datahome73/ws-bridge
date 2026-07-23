# R143 Step 5 🧪 测试报告 — 跨步状态同步修复轮

> **日期：** 2026-07-23
> **测试者：** 泰虾（QA）
> **测试模式：** 源码级分析 + 模拟验证
> **基线：** `1c30c95`（R143 Step 2 技术方案）
> **编码：** `8900c4f`（修复 commit）
> **审查：** `a7833b0`（审查通过）

---

## 测试范围

| # | 验收标准 | 类型 | 优先级 | 结果 |
|:-:|:---------|:----:|:------:|:----:|
| AS-1 | `##advance` 跳步后 `in_progress` 中间步 → `skipped` | 功能 | P1 | ✅ |
| AS-2 | `##advance` 跳步后 `done` 中间步保持 `done`（不降级） | 回归 | P1 | ✅ |
| AS-3 | 被跳过 step 清除 `dispatched_at` 字段 | 功能 | P1 | ✅ |
| AS-4 | 目标 step（跳到的步）保持 `in_progress` | 回归 | P1 | ✅ |
| AS-5 | `pending` 中间步 → `skipped`（与修复前一致） | 回归 | P1 | ✅ |
| AS-6 | 修复后 `in_progress` 中间步不触发超时扫描 | 验证 | P1 | ✅ |

## 测试详情（14/14 ALL GREEN 🟢）

### AST 源码验证（6 项）

| # | 检查项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| AS-0 | `_handle_hash_advance` 函数存在 | ✅ | L1254 定位成功 |
| AS-0a | 条件改为 `not in ("done",)` | ✅ | 旧条件 `in ("pending",)` 已替换 |
| AS-0b | `dispatched_at` 清除存在 | ✅ | `s.pop("dispatched_at", None)` 已添加 |
| AS-0c | `old_status` 在修改前保存 | ✅ | 日志记录原状态，非 `"skipped"` |
| AS-0d | 日志标记为 `[R143]` | ✅ | 日志前缀已更新 |
| AS-0e | done 步不被跳过 | ✅ | `not in ("done",)` 保护已存在 |

### 模拟逻辑验证（6 项）

| # | 场景 | 输入 | 预期 | 实际 | 结果 |
|:-:|:-----|:-----|:-----|:-----|:----:|
| AS-1 | in_progress 中间步跳步 | Step2=in_progress, 跳到 Step4 | Step2=skipped | skipped | ✅ |
| AS-2 | done 中间步不降级 | Step2=done, 跳到 Step4 | Step2=done | done | ✅ |
| AS-3 | dispatched_at 清除 | Step2=in_progress+dispatched_at, 跳到 Step4 | 无 dispatched_at | 已清除 | ✅ |
| AS-4 | 目标步保持 in_progress | 跳到 Step4 | Step4=in_progress | in_progress | ✅ |
| AS-5 | pending 中间步跳过（回归） | Step1-3=pending, 跳到 Step4 | 全 skipped | 全 skipped | ✅ |
| AS-6 | 超时扫描不触发 | 跳步后检查 Step2 | 不通过 L2221/L2224 | status=skipped,无 dispatched_at | ✅ |

### 超时扫描器双重保护验证（2 项）

| # | 检查项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| AS-6a | L2221: 跳过非 in_progress 步 | ✅ | 状态改为 skipped 后直接跳过 |
| AS-6b | L2224: 跳过无 dispatched_at 步 | ✅ | dispatched_at 清除后直接跳过 |

---

## 改动确认

### 文件变更

| 文件 | 改动 | 行数变化 |
|:----|:-----|:--------:|
| `server/ws_server/pipeline_engine.py` | `_handle_hash_advance` 跨步条件 + 清理 + 日志 | +5/-3 |

### 核心代码（L1296-L1301）

```python
if step_num_i < step_num and s.get("status") not in ("done",):
    old_status = s.get("status", "unknown")
    s["status"] = "skipped"
    s.pop("dispatched_at", None)  # R143: 清除时间戳，防止超时扫描器误判
    logger.info("[R143] %s step%d → skipped（##advance 跨步，原状态=%s）",
                round_name, step_num_i, old_status)
```

### 语义变化

| 状态 | 旧行为 | 新行为 | 正确性 |
|:-----|:------:|:------:|:------:|
| pending | → skipped | → skipped | ✅ 一致 |
| **in_progress** | **→ 不动 ❌** | **→ skipped ✅** | ✅ 修复 |
| failed | → 不动 | → skipped | ✅ 合理 |
| done | → 不动 | → 不动 | ✅ not in ("done",) 不命中 |
| skipped | → 不动 | → 不动 | ✅ 幂等 |

---

**总结：14/14 ALL GREEN 🟢**
