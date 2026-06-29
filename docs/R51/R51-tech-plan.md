# R51 技术方案

> **基于需求：** [R51-product-requirements.md v0.2 ✅](./R51-product-requirements.md)
> **基于工作计划：** [WORK_PLAN.md v0.2 ✅](./WORK_PLAN.md)
> **日期：** 2026-06-29

## 改动点

**文件：** `server/handler.py` 第 1396 行

| 当前代码 | 改为 |
|:---------|:-----|
| `step_name = positional[0]` | `step_name = positional[0].lower()` |

**说明：** 将用户输入的 step 名归一化为小写，使 `!step_complete Step4`（大写 S）也能匹配 Task 名 `step4` 和 Step 映射表 key `step4`。

**影响范围：** 仅 `_cmd_step_complete()` 函数内的这一行。所有比较路径（Task 名、Step 映射表 key）都引用 `step_name` 变量，一处修改覆盖两处比较点的修复。

**向后兼容：** ✅ 全小写输入 `step4` 不受影响（`"step4".lower() == "step4"`）。已有 Task 均为小写名，升级后正常工作。

## 验证

- A-1：`!step_complete Step2 --output <sha>`（大写 S）→ 匹配成功
- A-2：`!step_complete step2 --output <sha>`（全小写）→ 不回归
- A-3：`!step_complete STEP2 --output <sha>`（全大写）→ 匹配成功
