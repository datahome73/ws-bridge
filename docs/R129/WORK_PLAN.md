# WORK_PLAN — R129 废弃代码清理（PipelineAutoStarter 退役）

> **轮次：** R129
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 待审

---

## 目标

删除 PipelineAutoStarter 全部代码 + 清理关联引用，净删 ~336 行。零新增。

---

## Step 分派计划

### Step 1 — PM 审核 (你)

- [ ] 审核 `R129-product-requirements.md`

### Step 2 — Arch (小开)

- [ ] 确认删除范围：3 个文件改动点
- [ ] 确认 `from_work_plan()` 无其他调用者

### Step 3 — Dev (爱泰)

- [ ] 删除 `server/ws_server/pipeline_auto_starter.py`
- [ ] `__main__.py` 去掉 import + PAS init 块 + `PAS_ENABLED` 读取
- [ ] `pipeline_context.py` 删除 `from_work_plan()` 方法和相关代码
- [ ] 清理 docs 引用 (`R119/*.md`, `inbox-message-protocol.md`, `TODO.md`)
- [ ] 每次改动后 `py_compile` 验证

### Step 4 — Review (小周)

- [ ] 确认无遗漏引用（`grep -rn "PipelineAutoStarter\|pipeline_auto_starter\|PAS_ENABLED\|from_work_plan" server/`）

### Step 5 — QA (泰虾)

- [ ] `py_compile` 全量零错误
- [ ] 启动验证：服务正常启动
- [ ] `##start` / `##status` / `##advance` 全部正常

### Step 6 — Ops (小爱)

- [ ] 合入 `dev` → 合入 `main` + tag → 部署（不需加 `PAS_ENABLED`）

---

## 改动预览

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| 🗑️ 删除 | `pipeline_auto_starter.py` | -211 |
| ✂️ 修改 | `__main__.py` | -35 |
| ✂️ 修改 | `pipeline_context.py` | -70 |
| ✂️ 修改 | 文档 | -20 |
| **总计** | | **-336 行** |
