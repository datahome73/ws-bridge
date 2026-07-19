# WORK_PLAN — R128 Bug 修复轮（B-1 ~ B-4）

> **轮次：** R128
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 待审

---

## 目标

修复 4 个管线相关 Bug，全部在 `main.py` 中，总计 ~29 行修改。

---

## Step 分派计划

### Step 1 — PM 审核 (你)

- [ ] 审核 `R128-product-requirements.md`

### Step 2 — Arch (小开)

- [ ] 确认 4 处修改范围和行号
- [ ] 确认 B-4 正则兼容性（不误匹配）
- [ ] 确认 B-2 重试退避策略

### Step 3 — Dev (爱泰)

- [ ] B-1: 删除 `_auto_dispatch` 中 `ms.save_message` 调用（L3118-3131）
- [ ] B-3: `status_icons["in_progress"] = "🔄"`（L3667 附近）
- [ ] B-4: `_try_advance_pipeline` 正则放宽（L2590）
- [ ] B-2: `_enqueue_retry` + 重试扫描器优化（L2817~L2800）
- [ ] 每改一处 `py_compile` 验证

### Step 4 — Review (小周)

- [ ] 确认 B-1 删除了正确的 `ms.save_message` 调用
- [ ] 确认 B-4 正则不会误匹配非完成消息
- [ ] 确认 B-2 重试退避逻辑正确

### Step 5 — QA (泰虾)

- [ ] `py_compile` 全量零错误
- [ ] B-1: Web 端 dispatch 只显示一条
- [ ] B-3: `##status` 显示 `🔄` 而非 `⬜`
- [ ] B-4: 三种格式的完成消息均能推进
- [ ] B-2: 离线 bot 重试逻辑

### Step 6 — Ops (小爱)

- [ ] 合入 `dev` → 合入 `main` + tag → 部署

---

## 关键里程碑

| 节点 | 预计产出 | 完成标记 |
|:-----|:---------|:--------:|
| 需求文档审核通过 | `docs/R128/` 推 dev | ⬜ |
| Dev 编码 + py_compile | 4 处修改全部到位 | ⬜ |
| QA 验收通过 | 13 项验收全绿 | ⬜ |
| 合入 main | 部署完成 | ⬜ |
