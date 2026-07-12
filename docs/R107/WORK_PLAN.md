# R107 WORK_PLAN — 消除重复代码 + 自动派活功能落地（代码完成，不通电）

> **轮次：** R107
> **日期：** 2026-07-13
> **auto_chain:** false
> **说明：** 本轮只装自动派活的最后一个轮子——写完全部代码，默认关闭。下轮 R108 再启用跑全自动流水线。
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱

---

## 步骤

### Step 1 — PM 审核确认

需求文档审核通过后，标记已审核，推 dev。

**产出：** commit `docs(R107): Step 1 ✅ WORK_PLAN 已审核 — 管线启动`

---

### Step 2 — 架构师（小开）技术方案

评估以下内容并输出技术方案文档：

1. `_handle_server_relay` 两副本消除方式 — 保留哪个副本、调用点替换方案
2. Pipeline Context 4 新字段的 dataclass 插入点（to_dict/from_dict 同步）
3. `_render_template` 函数设计（变量来源优先级）
4. `_auto_dispatch` 函数设计 + `AUTO_DISPATCH_ENABLED` 开关位置
5. 同步函数中启动 async 协程的方式（`asyncio.ensure_future`）
6. 最后一步完成后标记 completed 的逻辑

**产出：** `docs/R107/r107-step2-tech-plan.md`

---

### Step 3 — 开发（爱泰）编码实现

1. **`server/config.py`**：新增 `AUTO_DISPATCH_ENABLED = False`（或环境变量）
2. **`server/pipeline_context.py`**：新增 `round_title/references/artifacts/message_templates` 4 字段，同步 to_dict/from_dict
3. **`server/main.py`**：
   - 删除 `_handle_server_relay` 副本 2（L2628-L2830），副本 2 调用点改为调副本 1
   - 新增 `_render_template(template, ctx, step_num)` 函数
   - 新增 `_auto_dispatch(ctx, step_num) async` 函数（受 `AUTO_DISPATCH_ENABLED` 控制）
   - 新增 `_get_step_agent_name(ctx, step_num)` 辅助函数
   - 在 `_try_advance_pipeline` 成功推进后插入：
     - `asyncio.ensure_future(_auto_dispatch(ctx, next_step))`（开关关闭时只打日志）
     - 最后一步完成后 `ctx.status = PipelineStatus.COMPLETED`
4. 单元测试：写一个最小测试验证 `_render_template` 变量替换正确

**产出：** commit `feat(R107): Step 3 - 消除重复代码 + 自动派活功能落地 (开关关闭)`

---

### Step 4 — 审查（小周）代码审查

审查以下文件的 diff：
- `server/main.py`（-200 + ~85 行）
- `server/pipeline_context.py`（+15 行）
- `server/config.py`（+3 行）

**重点关注：**
- 副本 2 删除后零引用 ✓
- 开关关闭时绝对不发送消息 ✓
- 向后兼容（旧 context 反序列化正常） ✓

**产出：** 审查意见

---

### Step 5 — 测试（泰虾）验证

验证 9 项验收标准：

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | `_handle_server_relay` 只有一份 | `grep -c` 检查 |
| 2 | 4 新字段序列化正确 | 创建 → to_dict → from_dict → 字段值不变 |
| 3 | `_render_template` 渲染正确 | 传入模板 + ctx，验证 `{round}`→`R107` 等替换 |
| 4 | `_auto_dispatch` 存在可调用 | 函数引用检查 |
| 5 | 开关关闭时不发消息 | 日志含 `[R107] 自动派活已关闭`，无实际发送 |
| 6 | 无上下文不执行 | 旧消息格式不受影响 |
| 7 | 最后一步标记 completed | `ctx.status == "completed"` |
| 8 | 多轮次并行 | 两个独立 round_name 互不干扰 |
| 9 | 开关关闭时无行为变化 | 手工派活照常，无延迟 |

**产出：** `docs/R107/R107-test-report.md`

---

### Step 6 — 部署（小爱）合并 main + 镜像重建

1. PR: dev → main
2. 重建 Docker 镜像 `ws-bridge:r107`
3. 重启 Supervisor 双进程
4. **验证：** 重启后手工派活一次，确认管线操作不受影响

---

## 依赖关系

```
Step 1 (PM) ─→ Step 2 (arch) ─→ Step 3 (dev) ─→ Step 4 (review) ─→ Step 5 (qa) ─→ Step 6 (ops)
```

---

## 下轮预告：R108

R107 部署后，下轮 R108 只需：
1. `AUTO_DISPATCH_ENABLED = True`
2. 跑一次全 6 步流水线，验证自动派活链路
3. 验证通过后合并部署
