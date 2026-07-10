# R91 测试验证报告 — workspace 阻塞修复 + 错误信息细化 🔧

> **测试人：** 🦐 泰虾
> **编码 SHA：** `2975e4e`
> **改动范围：** `server/workspace.py` (+3/-2) + `server/handler.py` (+16/-1)
> **参考文档：**
> - 产品需求: `docs/R91/R91-product-requirements.md`
> - 技术方案: `docs/R91/R91-tech-plan.md`

---

## 测试结论：🟢 全部通过

**31 项测试断言，31 ✅ 通过，0 ❌ 失败 — 100.0%**

| 维度 | 断言数 | 通过 | 失败 |
|:-----|:------:|:----:|:----:|
| 🅰️ max_per_person 可配置化 | 5 | 5 | 0 |
| 🅱️ 错误信息分支细化 | 6 | 6 | 0 |
| 🅲 AutoRouter _admin 回归 | 6 | 6 | 0 |
| 函数级 + 回归验证 | 14 | 14 | 0 |

---

## 🅰️ max_per_person 可配置化 (🅰️-1 ~ 🅰️-2)

### 🅰️-1 默认 3，第 2 个工作室创建成功 🟢

| # | 测试内容 | 结果 | 说明 |
|:-:|:---------|:----:|:-----|
| 1a | `create_workspace()` 默认值 3 | 🟢 | `os.environ.get("MAX_ACTIVE_WORKSPACES", "3")` |
| 1b | `can_create_for()` 默认值 3 | 🟢 | `def can_create_for(owner_id: str, max_active: int = 3)` |
| 1c | 原硬编码 `max_per_person = 1` 已移除 | 🟢 | 旧值完全替换 |

**改动验证：** workspace.py +3/-2，最小改动。

### 🅰️-2 MAX_ACTIVE_WORKSPACES 环境变量生效 🟢

| # | 测试内容 | 结果 | 说明 |
|:-:|:---------|:----:|:-----|
| 2a | `import os` 存在 | 🟢 | |
| 2b | `os.environ.get("MAX_ACTIVE_WORKSPACES")` | 🟢 | 环境变量读取 |

---

## 🅱️ 错误信息分支细化 (🅱️-1 ~ 🅱️-2)

### 🅱️-1 超限时提示「活跃工作区过多」 🟢

| # | 测试内容 | 结果 | 说明 |
|:-:|:---------|:----:|:-----|
| 1a | `active_count` + `get_all_workspaces()` 遍历 | 🟢 | 计算当前活跃数 |
| 1b | 错误信息含 count/max | 🟢 | `管理者名下已有 N/3 活跃工作室` |
| 1c | `!close_workspace` 操作提示 | 🟢 | 明确可用命令 |

### 🅱️-2 重名时提示「已存在」 🟢

| # | 测试内容 | 结果 | 说明 |
|:-:|:---------|:----:|:-----|
| 2a | `get_workspace(ws_id)` 判断 | 🟢 | 精确区分重名 |
| 2b | 错误信息含「已存在」+ `--workspace-id` 建议 | 🟢 | 附着或关闭 |
| 2c | 旧模糊消息「可能已存在，或管理员名下活跃工作区过多」已移除 | 🟢 | 替换为精确分支 |

**错误消息对比：**

| 场景 | 旧消息（模糊） | 新消息（精确） |
|:-----|:--------------|:---------------|
| 重名 | ❌ 创建失败：{name} 可能已存在，或管理员名下活跃工作区过多 | ❌ 创建失败：工作室「{name}」已存在。→ 使用 `--workspace-id` 或 `!close_workspace` |
| 超限 | 同上（混在一起） | ❌ 创建失败：管理者名下已有 N/3 活跃工作室。→ 请先 `!close_workspace` |

---

## 🅲 AutoRouter _admin 信号回归 (🅲-1)

验证 R90 引入的 AutoRouter `_admin` 白名单模式未在 R91 中被影响（handler.py 有修改）：

| # | 测试内容 | 结果 | 说明 |
|:-:|:---------|:----:|:-----|
| 1a | `is_pm_inbox` 变量保留 | 🟢 | `_handle_message()` 内 |
| 1b | `is_admin` 变量保留 | 🟢 | 白名单模式 |
| 1c | `if not is_pm_inbox and not is_admin: return` 保留 | 🟢 | 通道过滤 |
| 1d | `_admin` 可触发管线就绪 | 🟢 | `"管线已启动" in content` |
| 1e | Step 完成仅 `is_pm_inbox` | 🟢 | 安全隔离 |
| 1f | `_on_pipeline_ready` 存在 | 🟢 | 函数未删除 |

---

## 回归验证

| 检查项 | 结果 | 说明 |
|:-------|:----:|:-----|
| workspace.py 最小改动 | 🟢 | +3/-2 |
| handler.py 改动范围 | 🟢 | +16/-1，仅 `_cmd_create_workspace()` |
| AutoRouter 核心函数全部保留（10 个） | 🟢 | `_on_pipeline_ready`, `_handle_message`, `_on_step_complete`, `_dispatch_step`, `_notify_all_done`, `_fetch_topology`, `_timeout_check_loop`, `_check_step_timeouts`, `_send_inbox`, `_send_to_pm` |
| R90 env var 守卫保留 | 🟢 | `_STEP_TIMEOUT_ENABLED` + `AR_STEP_TIMEOUT` |

---

## 汇总

| 维度 | 通过率 |
|:-----|:------:|
| 🅰️ max_per_person 可配置化 | **5/5 ✅ 100%** |
| 🅱️ 错误信息分支细化 | **6/6 ✅ 100%** |
| 🅲 AutoRouter _admin 回归 | **6/6 ✅ 100%** |
| 回归验证 | **14/14 ✅ 100%** |
| **总计** | **31/31 🟢 100%** |

**最终结论：🟢 全部通过** — 无阻断性问题。
- 🅰️ `max_per_person` 从硬编码 1 → 环境变量默认 3，+3/-2 最小改动
- 🅱️ 错误消息从模糊混合 → 精确分支（重名 vs 超限），+16/-1
- 🅲 AutoRouter R90 `_admin` 白名单完整保留，零回归
- `MAX_ACTIVE_WORKSPACES` 环境变量可自由配置（`export MAX_ACTIVE_WORKSPACES=N`）

---

*报告编写: 🦐 泰虾 · 2026-07-10*
