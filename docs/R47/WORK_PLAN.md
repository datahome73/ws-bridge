# R47 工作计划 — 进度 Tab 内容修复

- **轮次：** R47
- **类型：** Bug 修复（F-14） + 通知补全
- **日期：** 2026-06-27
- **文档作者：** 小谷（PM）

---

## 阶段总览

| 阶段 | 内容 | 负责人 | 预计 |
|:-----|:------|:-------|:-----|
| **Phase 1** | 代码修改 | 小开（arch）+ 爱泰（dev） | 30min |
| **Phase 2** | 编码审查 + 合并 main + 部署 | 小周（review）+ 小爱（admin） | 15min |
| **Phase 3** | 触发管线 + 验证 | 小谷（PM） | 20min |

---

## Phase 1 — 代码修改（小开/爱泰）

### Step 1：修复 F-14 — `get_tasks_by_context` → `list_tasks_by_context`

**文件：** `handler.py`

需要精确定位是哪些方法调用了错误的函数名。基于 `git grep`：

```bash
cd /tmp/ws-bridge-r47
grep -n 'get_tasks_by_context' handler.py
```

预期找到 2+ 处，全部替换为 `list_tasks_by_context`。

### Step 2：追加 `_task_notify_workspace()` 调用

**文件：** `handler.py`

在以下两处插入 `_task_notify_workspace()` 调用：

1. `_cmd_pipeline_start()` 中，在创建频道并退出后（让队友先入座），在发送点名之前或之后，调用 `_task_notify_workspace()` 写入初始 `📊` 消息。
2. `_cmd_step_complete()` 中，在 `set_step_complete()` 之后（状态已变更），调用 `_task_notify_workspace()` 更新同一条 `📊` 消息。

**注意事项：**
- `_task_notify_workspace(workspace, context, is_final=False)` 签名 — 检查调用的参数传递。
- 确保不会重复发送多条 `📊` 消息（`_task_notify_workspace` 内部应已有编辑机制）。
- step_complete 通知放在回复 Step 消息之前（让数据先更新到 _admin）。

### Step 3：关闭清理

**文件：** `handler.py`

在 `_cmd_workspace_close()` 或最后 Step 完成的路径中，调用 `_task_notify_workspace(workspace, context, is_final=True)` 让进度 Tab 标记为已关闭。

---

## Phase 2 — 编码审查 + PR + 部署（小周/小爱）

### Step 4：审查

确认：
- [ ] 所有 `get_tasks_by_context` 调用全部修正
- [ ] `pipeline_start` 中有 `_task_notify_workspace` 调用
- [ ] `step_complete` 中有 `_task_notify_workspace` 调用
- [ ] workspace_close 或 final step 有进度清理
- [ ] 不引入新的未引用导入或死代码

### Step 5：PR → 合并 main

```bash
cd /tmp/ws-bridge-r47
git add -A
git commit -m "R47 fix: F-14 function name + task notification chain"
git push origin dev
# 创建 PR dev → main，合并
```

### Step 6：部署

通知 小爱 重新部署生产容器（`docker compose restart ws-bridge` 或 `docker compose up -d --build`）。

---

## Phase 3 — 管线触发 + 验证（小谷）

### Step 7：创建管线

向 `_admin` 频道发送：
```
!pipeline_start R47
```

### Step 8：验证

| 验证项 | 预期 | 实际 |
|:-------|:-----|:-----|
| `📊` 初始消息 | 创建管线后在 `_admin` 可见 | |
| `!pipeline_status` | 返回当前 Step 的任务清单 | |
| `!step_complete` 后 | `📊` 消息更新 Step 状态 | |
| 工作室关闭 | `📊` 标记为已关闭 | |

### Step 9：收尾

所有验证通过后：
- [ ] 更新 `docs/TODO.md` 标记 F-14 为 🟢
- [ ] 更新 R47 文档状态
- [ ] 将 R47 文档推送到 dev

---

## 回退方案

本轮回滚极其简单：仅 `handler.py` 修改，从 git revert 然后重新部署即可。生产环境不受数据完整性问题影响。
