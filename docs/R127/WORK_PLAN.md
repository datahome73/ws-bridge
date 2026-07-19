# WORK_PLAN — R127 管线状态机提取

> **轮次：** R127
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 待审

---

## 目标

将 `main.py` 中的管线状态机逻辑（~2000 行 / 45 个函数）提取到 `pipeline_engine.py` 的 `PipelineEngine` 类中。纯搬移，不改任何业务逻辑。

---

## Step 分派计划

### Step 1 — PM 审核 (你)

- [ ] 审核 `R127-product-requirements.md`
- [ ] 确认范围：纯搬移不改逻辑
- [ ] 确认不做事项：不改 `pipeline_context`/`task_card`，不新加功能

### Step 2 — Arch 架构设计 (小开)

- [ ] 设计 `PipelineEngine` 类接口签名 (~28 个方法)
- [ ] 确定 `ws_client_factory` 回调形式
- [ ] 确定后台扫描循环统一启动方式 (`engine.start()`)
- [ ] 编写骨架代码（空方法体 + docstring）
- [ ] 输出 `docs/R127/R127-tech-plan.md`

### Step 3 — Dev 编码 (爱泰)

- [ ] 逐函数搬移管线代码到 `PipelineEngine`
- [ ] 修改 `main.py` — 替换为 `self._engine.*` 调用
- [ ] 修改 `scenario_matcher.py` — `_sm_handle_*` 改引用
- [ ] 修改 `__main__.py` — 后台任务改 `engine.start()`
- [ ] 修改 `pipeline_auto_starter.py` — 改引用
- [ ] 每搬 5~8 个函数做一次 `py_compile` 验证

### Step 4 — Review (小周)

- [ ] 全量 `grep -n` 扫描 `_handle_hash\|_try_advance\|_auto_dispatch` 等旧引用
- [ ] 确认无残留直接调用
- [ ] 检查 import 完整性
- [ ] 输出 `docs/R127/R127-code-review.md`

### Step 5 — QA (泰虾)

- [ ] `py_compile` 全量零错误
- [ ] 运行时管线全流程测试：
  - `##start##R127-test`
  - `##status##R127-test`
  - `##advance##R127-test##step=2`
  - `##stop##R127-test`
  - `##archive##R127-test`
- [ ] `✅ 完成` 推进测试
- [ ] 启动后后台扫描循环正常
- [ ] 输出 `docs/R127/R127-test-report.md`

### Step 6 — Ops (小爱)

- [ ] 合入 `dev`
- [ ] 合入 `main` + tag
- [ ] 部署生产
- [ ] 验证生产运行正常

---

## 关键里程碑

| 节点 | 预计产出 | 完成标记 |
|:-----|:---------|:--------:|
| 需求文档审核通过 | `docs/R127/` 推 dev | ⬜ |
| Arch 骨架完成 + 审核 | `pipeline_engine.py` 骨架 | ⬜ |
| Dev 编码 + py_compile 通过 | 全部 45 个函数搬移完成 | ⬜ |
| Review 引用完整性扫描 | 零残留引用 | ⬜ |
| QA 全流程通过 | PE-1~11 + RV-1~5 全部通过 | ⬜ |
| 合入 main | 6/6 ALL DONE | ⬜ |

---

## 附录：搬移优先级

| 批次 | 函数 | 数量 | 验证方式 |
|:----:|:-----|:----:|:---------|
| **A** | 纯数据/工具函数: `_format_pipeline_context` / `_render_template` / `_get_step_agent_name` / `_build_step_summary` / `_find_archive` / `_enqueue_retry` | 6 | py_compile |
| **B** | 状态推进: `_try_advance_pipeline` / `_auto_advance_pipeline` | 2 | py_compile + 运行时测试 |
| **C** | ## 命令: `_handle_hash_*` x5 + `_archive_pipeline` | 6 | 运行时测试 |
| **D** | 自动调度: `_auto_dispatch` / `_auto_swap_agent` / `_auto_re_notify` | 3 | 运行时测试 |
| **E** | 通知/回退: `_notify_pm` / `_handle_reject` | 2 | 运行时测试 |
| **F** | 后台扫描: `_pipeline_git_sync_scan` / `_pipeline_timeout_scan` / `_restore_*` | 5 | 启动验证 |
| **G** | _sm_handle_* 改引用 + __main__.py 改启动 | ~10 | py_compile + 启动验证 |
