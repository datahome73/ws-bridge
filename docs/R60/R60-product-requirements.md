# R60 产品需求 — 系统消息中 agent ID → 角色名/ bot 名 显示

> **版本：** v1.0
> **状态：** 📝 初稿（待项目负责人审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-30
> **本轮改动范围：** 仅 `server/handler.py` — 系统消息中 agent ID 的渲染层替换
> **参考：** TODO F-19（🟢 P3）

---

## 1. 问题背景

当前 `_admin` 频道和工作室的系统消息中，列举成员时使用原始 agent ID（`01KTNJ2QQ...` 格式），对 Web 端观察者不直观且暴露内部标识。

| 场景 | 现状 | 问题 |
|:-----|:-----|:-----|
| `_admin` 系统消息中的成员列表 | `01KTNJ2QQ...` 等随机字符串 | Web 观察者无法对应到具体角色 |
| `_cmd_step_complete` 后台通知 | 部分路径使用 `agent_id[:12]` | 不统一，部分用名部分用 id |
| `_notify_member_changed` | fallback `member_id[:12]` | 应优先展示 role / display_name |
| 现有 `_cmd_create_workspace` | ✅ 已用 `users.get(name)` | 保持不动 |
| 现有 `_cmd_pipeline_status` | ✅ R57 已加名称解析 | 保持不动 |

### 设计原则

> **统一策略：** agent 展示需按优先级查找
> 1. `agent_card.display_name`（Agent Card 配置的显示名）
> 2. `auth.get_users()[aid].name`（bot 注册名）
> 3. `auth.get_users()[aid].role`（管线角色：arch/review/qa 等）
> 4. 最终回退 `aid[:12]`（截断 ID，仅异常路径）
>
> 此策略复用现有 `_cmd_pipeline_status` 的 R57 逻辑（line 2114-2118），统一全系统各处。

---

## 2. 功能需求

### 方向 A（核心）：`_admin` 系统消息 agent ID → 角色名 🔴 P0

**目标：** 所有 `write_chat_log("系统", ...)` 和 `_persist_admin_response` 中涉及 agent ID 的地方，替换为可读名称。

受益代码路径：

| # | 位置 | 当前代码 | 替换为 |
|:-:|:-----|:---------|:-------|
| A1 | `_handle_auth` 注册通知 (L205) | `{agent_id[:16]}` | `{_get_agent_display(agent_id)}` |
| A2 | `_handle_auth` 注册 admin 通知 (L210) | `{agent_id[:16]}` | 同上 |
| A3 | `_r57_switch_to_backup` swap broadcast (L1716-1718) | `{primary_name}`（已有名 ✅） | 保持不变 |
| A4 | `_persist_admin_response` 通用传递 | 使用 `from_name` 字段 ✅ | 保持不变 |
| A5 | `_notify_member_changed` fallback (L3140) | `member_id[:12]` | `_get_agent_display(member_id)` |
| A6 | 其他 `write_chat_log("系统", ...)` 中原始 agent ID 引用 | 逐个扫描 | 统一替换 |

### 方向 B（辅助）：提取通用 `_get_agent_display()` 工具函数 🟡 P2

```python
def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
    cards = _load_agent_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]
```

**注意：** auth.get_users() 是全量读取。若性能敏感，可引入短生命周期缓存（5s TTL）。

### 方向 C（可选）：agent Card display_name 预设 👁️ P3

如果部分 bot 尚未配置 Agent Card 的 `display_name`，可由 PM 逐一查看并补全 `!agent_card set <id> display_name=Bot名`。本步骤**不阻塞编码**，可在测试阶段补充。

---

## 3. 验收标准

| # | 检查项 | 预期 |
|:-:|:-------|:-----|
| ✅-1 | `_admin` 注册通知显示 bot 名而非 agent ID | `新代理注册请求：Bot名（全名）已连接` 而非 `新代理注册请求：Bot名（01KTN...）已连接` |
| ✅-2 | `_notify_member_changed` 显示角色/名 | `xxx 加入了工作室` 而非 `01KTN... 加入了工作室` |
| ✅-3 | 工具函数 `_get_agent_display()` 优先级正确 | display_name > name > role > agent_id[:12] |
| ✅-4 | 现有 `_cmd_pipeline_status` 成员显示不受影响 | 行为不变（已使用 name/role 逻辑） |
| ✅-5 | 100% 回归——所有修改不影响现有逻辑 | 现有 38 项 R58 测试 + R57 测试全部通过 |
| ✅-6 | shell/grep 验证零残留 agent ID 在系统消息中 | `grep -n 'agent_id\[.*:' server/handler.py` 确认仅余日志/注册通道等合法引用 |

---

## 4. 不纳入范围

| 事项 | 说明 |
|:-----|:------|
| Web 端渲染调整 | Web 前端已通过 `from_name` 字段显示名称，不需改 |
| !pipeline_status 改造 | R57 已完成（lines 2114-2121 ✅） |
| !agent_card 命令增强 | 已有完整 CRUD，本轮不动 |
| 系统日志（logger.info）中的 agent ID | 日志是运维工具，保留 ID 用于 Debug |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ 需求审核 | 项目负责人 | 审核通过/修改意见 | ⏳ |
| **Step 1** | 📋 需求分析师 (PM) | WORK_PLAN.md（技术任务拆分） | 10min |
| **Step 2** | 👷 架构师 (Arch) | 技术方案（改哪里、怎么改、测试策略） | 15min |
| **Step 3** | 👨‍💻 开发工程师 (Dev) | 编码 + `R60_test.py`（含语法检查 + 31+cases） | 20min |
| **Step 4** | 👀 审查工程师 (Review) | 代码审查 + 脱敏检查 | 15min |
| **Step 5** | 🦐 测试工程师 (QA) | 测试报告 + 分支覆盖 | 15min |
| **Step 6** | 🛠️ 项目管理 (Admin) | 合并部署 + TODO.md 更新 + 归档 | 10min |

> **预估总耗时：** ~85 min（不含需求审核）
> **管线模式：** 🚀 自动驾驶（Auto）

---

## 6. 脱敏检查清单（推前强制）

- [ ] `docs/R60/*.md` — 无内部名残留
- [ ] 代码 diff — 无内部名/URL/端口泄露
- [ ] `grep -n '需求分析师\|项目管理\|架构师\|开发工程师\|审查工程师\|测试工程师\|项目负责人\|datahome73\|wsim\.'` 零匹配

---

> **项目负责人审核区：**
>
> 方向选择：□ F-19（角色名显示） □ 其他 ________
> 管线模式：□ 🚀 自动 □ 📋 手动
> 备注：____________________
