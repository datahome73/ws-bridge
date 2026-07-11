---
pipeline:
  name: "R100 服务端核心重构：handler.py 拆分 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/R100-product-requirements.md"

  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 结构设计
        context:
          requirements_url: "${pipeline.requirements_url}"
      - step: step3
        role: developer
        title: 编码拆分
        context:
          requirements_url: "${pipeline.requirements_url}"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署归档
        context:
          test_report_url: "docs/{round}/{round}-test-report.md"

  steps:
    step2:
      role: architect
      title: 结构设计
    step3:
      role: developer
      title: 编码拆分
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署归档

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "产出结构设计方案（8 文件拆分路径 + 47 命令映射表 + 依赖关系）"
      developer:
        mention_keyword: "developer;开发"
        rules: "6 步编码执行：state.py → command_utils.py → commands/ → main.py → __main__.py 更新 → 验证"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查拆分质量（核心/插件分层、无循环导入、inbox 通路保留）"
      qa:
        mention_keyword: "qa;测试"
        rules: "执行验收 15 项：5 核心通路 + 5 命令功能 + 5 代码质量"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署 + 验证 inbox 双向通信正常"
---

# R100 工作计划 — 服务端核心重构：handler.py 拆分 🏗️

> **版本：** v1.0
> **状态：** 📝 初稿
> **负责人：** 🧐 PM
> **前置条件：** R99 部署完成 ✅ (v2.68, main 9c0c5b8)

---

## 概述

将 `server/handler.py`（7024 行）按"核心消息路由 vs 插件命令"分层原则拆分为 8 个文件。**只做结构拆分，零行为变更。**

### 分层原则

```
消息通道（核心）— 去掉则 inbox 不通
  ├── main.py  (~800行)  改名+精简
  └── handler() + handle_broadcast + relay + query

插件（附加）— 去掉 inbox 仍通
  ├── state.py          共享状态
  ├── command_utils.py  命令路由工具
  └── commands/         !命令处理（5领域）
```

### 核心测试

> 重构前后，bot A 向 bot B 发 _inbox 消息必须完全不受影响。

### 改动范围

| 文件 | 动作 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` → `server/main.py` | 改名+精简 | 7024 → ~800 |
| `server/state.py` | 🔺 新增 | ~200 |
| `server/command_utils.py` | 🔺 新增 | ~200 |
| `server/commands/__init__.py` | 🔺 新增 | ~100 |
| `server/commands/workspace.py` | 🔺 新增 | ~500 |
| `server/commands/pipeline.py` | 🔺 新增 | ~1200 |
| `server/commands/agent_card.py` | 🔺 新增 | ~300 |
| `server/commands/task.py` | 🔺 新增 | ~400 |
| `server/commands/admin.py` | 🔺 新增 | ~200 |
| `server/__main__.py` | import 路径更新 | ~5 行改 |
| **合计** | **8 新增 + 2 修改** | **~3900 行** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 写需求 + WORK_PLAN | R100-product-requirements.md + WORK_PLAN.md | 推 dev ✅ |
| **Step 2** | 👷 Arch | 结构设计 | 已产出server/README.md（架构图 + 依赖关系 + 文件职责） | 推 dev ✅ |
| **Step 3** | 👨‍💻 Dev | 编码拆分 — 6 步执行 | 全部代码文件拆分 | 见下 |
| **Step 4** | 👀 Review | 代码审查 | R100-code-review.md | 推 dev |
| **Step 5** | 🦐 QA | 测试验证 | R100-test-report.md（15 项验收） | 推 dev |
| **Step 6** | 🛠️ Ops | 合并 dev→main + 部署 | Docker 新镜像 + 生产验证 | TODO.md 更新 |

---

## Step 3 编码拆分（Dev — 6 步执行）🔧

### Step 3.1 — 创建 state.py

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev |
| 做什么 | 从 handler.py 复制全部模块级全局变量到新文件 `server/state.py` |
| 清单 | `_PIPELINE_STATE`, `_PIPELINE_CONFIG`, `_ROLE_AGENT_MAP`, `_step_ack_states`, `_pipeline_manager`, `_GIT_SYNC_TASK`, `_LOBBY_PAUSED`, `_LOBBY_PAUSED_ROUND`, `_step_advance_buffer`, `_r57_rollcall_events`, `_watchdog_started`, `_watchdog_task`, `_watchdog_alerts`, `_offline_timers`, `_r72_users`, `_delivery_status`, `_offline_push_queue`, `SYSTEM_AGENT_ID`, `REGISTRATION_BROADCAST_ENABLED`, `SERVER_INBOX_CHANNEL`, `is_server_inbox()`, `_task_ack_timers`, `_rate_limits`, `_last_message`, 消息常量, `_channel_ack_state`, `_card_watcher_running` |
| 验证 | `python3 -c "from server.state import _PIPELINE_STATE"` 无报错 |

### Step 3.2 — 创建 command_utils.py

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev |
| 做什么 | 从 handler.py 复制命令路由工具函数到 `server/command_utils.py`，引用改为 `state.X` |
| 清单 | `_admin_msg()`, `_persist_admin_response()`, `_send_cmd_response()`, `_parse_command()`, `_is_any_workspace_admin()`, `_log_audit()`, `_check_command_permission()`, `_resolve_workspace()` |
| 验证 | `python3 -c "from server.command_utils import _parse_command; print(_parse_command('!test --key val'))"` |

### Step 3.3 — 创建 commands/ 包

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev |
| 做什么 | 创建 `server/commands/` 目录 + `__init__.py` + 5 个领域文件 |
| 文件 | `workspace.py`, `pipeline.py`, `agent_card.py`, `task.py`, `admin.py` |
| **workspace.py** | `_cmd_create_workspace`, `_cmd_close_workspace`, `_cmd_list_workspaces`, `_cmd_workspace_join`, `_cmd_workspace_leave`, `_cmd_workspace_add`, `_cmd_workspace_remove`, `_cmd_workspace_list_members`, `_cmd_workspace_reset` |
| **pipeline.py** | `_cmd_pipeline_start`, `_cmd_pipeline_stop`, `_cmd_pipeline_status`, `_cmd_pipeline_activate`, `_cmd_pipeline_context`, `_cmd_pipeline_mode`, `_cmd_pipeline_role_override`, `_cmd_step_handoff`, `_cmd_step_complete`, `_cmd_step_reject`, `_cmd_step_force`, `_cmd_step_verify` + 全部管线辅助函数（约 30 个） |
| **agent_card.py** | `_cmd_agent_card_list`, `_cmd_agent_card_get`, `_cmd_agent_card_set`, `_cmd_agent_card_unset`, `_cmd_agent_card_reload`, `_cmd_agent_card_register`, `_cmd_agent_card_auto_register`, `_cmd_agent_role_map` |
| **task.py** | `_cmd_task_create`, `_cmd_task_update`, `_cmd_task_query`, `_cmd_task_list`, `_cmd_rollcall_role`, `_cmd_rollcall_next` |
| **admin.py** | `_cmd_approve_ws_admin`, `_cmd_reject_ws_admin`, `_cmd_list_pending`, `_cmd_audit_log`, `_cmd_list_workspace_admins`, `_cmd_list_agents`, `_cmd_agent_status`, `_cmd_revoke_api_key` |
| 关键改法 | 每个命令函数中：`_PIPELINE_STATE` → `state._PIPELINE_STATE`, `_broadcast_to_channel()` → `command_utils._broadcast_to_channel()`, `_send_cmd_response()` → `command_utils._send_cmd_response()`, `_log_audit()` → `command_utils._log_audit()` |
| 验证 | `python3 -c "from server.commands import _ADMIN_COMMANDS; print(len(_ADMIN_COMMANDS))"` 返回 47 |

### Step 3.4 — handler.py → main.py

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev |
| 做什么 | `git mv server/handler.py server/main.py`，删除已搬出的函数和变量，保留核心 ~800 行，添加新 import |
| 保留 | `handler()`, `handle_broadcast()`, `_handle_server_relay()`, `_handle_server_query()`, `handle_auth()`, `handle_register()`, `handle_agent_card_register()`, `_send()`, `_connections`, `_force_disconnect_revoked_agent()`, `get_connections()`, `get_delivery_status()`, msg_type 分支 |
| 验证 | 服务启动无 ImportError |

### Step 3.5 — 更新 __main__.py

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev |
| 做什么 | 改 import 路径：`from .main import ...` 替代 `from .handler import ...` |
| 验证 | 服务正常启动 |

### Step 3.6 — 验证 + 部署

| 项 | 内容 |
|:---|:------|
| 谁做 | 👨‍💻 Dev → 🛠️ Ops |
| 做什么 | 本地测试 → 推 dev → 代码审查 → QA 验收 → Ops 合并部署 |
| 验证 | 15 项验收标准全部通过 |

---

## 验收标准

### 核心通路（5 项）

```
1. Bot A 连接 → 认证成功
2. Bot A 向 Bot B 发 _inbox 消息 → Bot B 收到
3. Bot B 回复 Bot A 的 _inbox → Bot A 收到
4. _inbox:server 中继功能正常（ACK ✅ / ✅ 完成 路由到 PM）
5. 大厅 lobby 消息广播正常
```

### 命令功能（5 项）

```
6. !list_workspaces → 返回工作区列表
7. !pipeline_status → 返回管线状态（无错误）
8. !agent_card list → 返回 Agent Card 列表
9. !task_list → 返回任务列表
10. !audit_log → 返回审计日志
```

### 代码质量（5 项）

```
11. handler.py → main.py, 从 7024 ↓ ~800 行
12. commands/ 目录存在，包含 __init__.py + 5 个模块
13. state.py 存在，包含全部共享变量
14. command_utils.py 存在，包含全部工具函数
15. 无循环导入：服务启动无 ImportError
```

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R100/R100-product-requirements.md` |
| 工作计划 | `docs/R100/WORK_PLAN.md` |
| 架构文档 | `server/README.md` |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/` 下 8 新增 + 2 修改，零行为变更 |
| 测试 | 全部 15 项验收 🟢 通过 |
| 文档 | 审查报告 + 测试报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启服务 |
