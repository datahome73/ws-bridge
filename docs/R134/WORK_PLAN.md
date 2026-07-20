---
pipeline:
  name: "R134 — 代码精简轮：! 命令体系 + Workspace + AutoRouter 清理 🧹"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R134/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R134/R134-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 拆除方案设计
      - step: step3
        role: developer
        title: 编码清理
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署归档
steps:
  - name: step2
    agent_id: ws_3f7cdd736c1c
    agent_name: 小开
    title: 拆除方案设计
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码 — 5 批文件清理 + 函数迁移
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — 删除检验 + 迁移检验
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 26 项验收
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R134 工作计划 — 代码精简轮

> **版本：** v1.0
> **状态：** ✅ 已通过
> **负责人：** 🧐 PM

## 概述

清理 R131 / R132 迁移后残留的 `!` 命令死代码（整个 commands/ 目录 + command_utils.py + main.py 中 3 个代码段），以及已废弃的 Workspace 子系统（workspace.py + __main__.py handler + Web UI Tab）和 AutoRouter（auto_router.py）。总计移除约 **3,750 行（22%）**，server 目录从 33 文件/17,100 行降至 ~26 文件/13,350 行。

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + WORK_PLAN | `R134-product-requirements.md` + `WORK_PLAN.md` | 推 dev |
| **Step 2** 🟡 待执行 | 👷 小开 | 拆除方案确认 | `R134-tech-plan.md` | 推 dev |
| **Step 3** ⏳ | 👨‍💻 爱泰 | 编码 — 5 批清理 + 函数迁移 | 代码修改 | py_compile + runtime import |
| **Step 4** ⏳ | 👀 小周 | 代码审查 | `R134-code-review.md` | 推 dev |
| **Step 5** ⏳ | 🦐 泰虾 | 测试验证 26 项验收 | `R134-test-report.md` | 推 dev |
| **Step 6** ⏳ | 🛠️ 小爱 | 合并部署 | 合 main + 重启 | `##status` 确认 |

---

## 关键里程碑

| 阶段 | 交付物 |
|:-----|:-------|
| Step 1 ✅ | 需求文档审核通过 + 推 dev |
| Step 2 ✅ | 拆除方案确认（arch 产出 `R134-tech-plan.md`） |
| Step 3 ✅ | 5 批清理完成：A 批 ! 命令 5 文件删除 + main/scenario_matcher 清理 / B 批 _cmd_task_update 迁移 / C 批 pipeline.py 精简 / D 批 Workspace 清除 / E 批 auto_router.py 删除。py_compile 全部通过 |
| Step 4 ✅ | 代码审查通过（删除文件完整性 / 迁移函数正确性 / 未误删活跃引用） |
| Step 5 ✅ | 测试 26/26 ALL GREEN 🟢（CLN 12 项 / WKS 6 项 / RV 8 项） |
| Step 6 ✅ | 合 main + 部署完成 |

---

## Step 分派

### Step 1 ✅ — PM 需求（已完成）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R134/R134-product-requirements.md` |
| 工作计划 | `docs/R134/WORK_PLAN.md` |

### Step 2 🟡 — 架构方案（小开）

- 产出 `docs/R134/R134-tech-plan.md`
- 确认各批删除的文件依赖关系（无交叉引用残留）
- 确认 `_cmd_task_update` 移入 `pipeline_engine.py` 的签名适配方案
- 确认 `commands/pipeline.py` 精简后文件的新位置/命名（`commands/` 只剩 1 个文件，是否重命名并移到 `ws_server/` 下）
- 确认 workspace 删除后 `main.py` 中 `ws_mod.get_workspace()` 频道解析调用的替代方案（替换为 `_inbox:` 前缀检查或移除）
- 确认自动路由中没有其他文件依赖 workspace/commands
- 确认 auto_router.py 没有被任何内部引用

### Step 3 ⏳ — 编码（爱泰）

#### Batch A: `!` 命令体系文件删除（~1,340 行）

| # | 操作 | 文件 | 说明 |
|:-:|:----|:-----|:------|
| A1 | ❌ 删除 | `server/ws_server/commands/__init__.py` | `_ADMIN_COMMANDS` 注册表 |
| A2 | ❌ 删除 | `server/ws_server/commands/workspace.py` | `!workspace` 命令 handler |
| A3 | ❌ 删除 | `server/ws_server/commands/admin.py` | `!admin` 命令 handler |
| A4 | ❌ 删除 | `server/ws_server/commands/agent_card.py` | `!agent_card` 命令 handler |
| A5 | ❌ 删除 | `server/ws_server/command_utils.py` | 仅被 ! 命令使用的工具函数 |
| A6 | 🔧 修改 | `server/ws_server/main.py` L1596-1618 | 删除 `!` 命令 `handle_broadcast` 路由段 |
| A7 | 🔧 修改 | `server/ws_server/main.py` L2070-2170 | 删除 `_handle_server_query()` 函数及 `!list_workspaces` / `!pipeline_status` / `!agent_card` / `!my_id` / `!help` 处理 |
| A8 | 🔧 修改 | `server/ws_server/main.py` L4834-4838 | 删除 `_sm_handle_exclamation()` handler |
| A9 | 🔧 修改 | `server/ws_server/main.py` L4937-4943 | 删除 `match_exclamation` 规则注册 |
| A10 | 🔧 修改 | `server/ws_server/scenario_matcher.py` L155-158 | 删除 `match_exclamation()` 函数 |
| A11 | 🔧 清理 | `server/ws_server/commands/pipeline.py` | 删除 `import command_utils` / `import workspace as ws_mod` 引用（A5+A2 删除后） |
| **A12** | 🐛 **修复** | `server/ws_server/main.py` L3147-3148 | `_auto_dispatch` 中 `from_name: "小谷"` → `"系统"`，`agent_id: "ws_f26e585f6479"` → `state.SYSTEM_AGENT_ID`（派活消息发件人身份硬编码 bug） |

> 注意 A6 删除前检查 `handle_broadcast` 中 `is_task = bool(mention_names) or content.startswith("!")`（L1594），确认改为 `is_task = bool(mention_names)`。

#### Batch B: `commands/task.py` 删除 + `_cmd_task_update` 迁移（-197 行）

| # | 操作 | 文件 | 说明 |
|:-:|:----|:-----|:------|
| B1 | 🔧 迁移 | `server/ws_server/pipeline_engine.py` | 将 `_cmd_task_update` 函数（来自 `commands/task.py` L32-80）作为 `PipelineEngine` 内部方法迁入。签名从 `(sender_id, params)` 改为直接接收 task_store 调用所需参数。更新已有调用处（L413-425） |
| B2 | ❌ 删除 | `server/ws_server/commands/task.py` | 全文件删除 |
| B3 | 🔧 修改 | `server/ws_server/main.py` L52 | 删除 `from .commands.task import _cmd_task_update` 导入 |
| B4 | 🔧 修改 | `server/ws_server/main.py` L61 | 删除 `cmd_task_update=_cmd_task_update` 参数（改传内部方法引用） |

#### Batch C: `commands/pipeline.py` 精简（-~885 行）

保留的函数（被 scenario_matcher / pipeline_engine / main 使用）：
- `_cmd_step_complete` / `_cmd_step_reject` / `_cmd_step_force` / `_cmd_step_handoff`（scenario_matcher.handle_step 使用）
- `_get_step_config` / `_find_agents_by_role` / `_set_pipeline_state` / `_step_sort_key`（main.py PipelineEngine 初始化使用）
- `_render_context` / `_infer_artifact_url` / `_build_fallback_config` / `_build_fallback_steps` / `_get_agent_display` / `_get_agent_card_roles` / `_find_agents_by_role` / `_parse_scalar` / `_parse_frontmatter` / `_build_pipeline_config`（被保留函数调用的辅助函数）

删除的 handler（已被 `##` 命令替代）：
| 函数 | 行数 | 替代命令 |
|:-----|:----:|:---------|
| `_handle_pipeline_command` | 144 行 | `##start` |
| `_cmd_pipeline_start` | 139 行 | `##start` |
| `_cmd_pipeline_activate` | 45 行 | `##start` |
| `_cmd_pipeline_stop` | 66 行 | `##stop` |
| `_cmd_pipeline_status` | 155 行 | `##query##status` |
| `_cmd_pipeline_mode` | 27 行 | `##step` |
| `_cmd_pipeline_role_override` | 38 行 | `##step` |
| `_cmd_step_verify` | 59 行 | `##step##force` |
| `_send_inbox_task` | 111 行 | `to_agent` inbox 派活 |
| `_check_pm_or_admin` | 16 行 | 权限体系 |
| `_run_validation_hook` | 46 行 | 已废弃 |
| `pipeline_is_active` | 6 行 | 无引用 |
| `pipeline_exists` | 6 行 | 无引用 |
| `set_lobby_paused` | 6 行 | 无引用 |
| `_build_fallback_steps` 部分 | — | 重复定义 |

| # | 操作 | 文件 | 说明 |
|:-:|:----|:-----|:------|
| C1 | 🔧 精简 | `server/ws_server/commands/pipeline.py` | 删除上述 10+ 个 handler 函数及关联代码 |

#### Batch D: Workspace 子系统清除

| # | 操作 | 文件 | 说明 |
|:-:|:----|:-----|:------|
| D1 | ❌ 删除 | `server/ws_server/workspace.py` | 460 行，整个 Workspace CRUD/状态机/持久化 |
| D2 | ❌ 删除 | `server/ws_server/workspace_api.py` | 37 行，HTTP API 端点 |
| D3 | 🔧 修改 | `server/ws_server/__main__.py` | 删除 `from . import workspace as ws_mod`（L19）+ workspace msg_type handler 代码块（L124-210，6 个消息类型） |
| D4 | 🔧 修改 | `server/ws_server/main.py` L24 | 删除 `from . import workspace as ws_mod` 导入 |
| D5 | 🔧 修改 | `server/ws_server/main.py` | 删除 `ws_mod.get_workspace()` 频道解析调用 + `_broadcast_workspace_closing` / `_broadcast_workspace_closing_aiohttp` 等 workspace 相关函数 |
| D6 | 🔧 修改 | `server/web_ui/templates.py` | 删除 📂 工作区 Tab 相关 HTML/CSS/JS |
| D7 | 🔧 修改 | `server/web_ui/viewer.py` | 删除 `/api/workspaces` 代理路由 + workspace poll 函数 |
| D8 | 🧹 清理 | `data/workspaces.json` | 部署时清空或删除 |

#### Batch E: AutoRouter 删除

| # | 操作 | 文件 | 说明 |
|:-:|:----|:-----|:------|
| E1 | ❌ 删除 | `server/ws_server/auto_router.py` | 750 行，R129 确认退役的独立 CLI 脚本 |

#### 编译验证

全部修改完成后运行：

```bash
cd /opt/data/ws-bridge
for f in $(find server -name '*.py' ! -path '*/__pycache__/*' | sort); do
    python3 -c "import ast; ast.parse(open('$f').read()); print(f'✅ $f')" 2>&1 || echo "❌ $f"
done
echo "---"
python3 -c "from server.ws_server import main; print('✅ Runtime import OK')" 2>&1 || echo "❌ Runtime import failed"
python3 -c "from server.ws_server import __main__; print('✅ __main__ import OK')" 2>&1 || echo "❌ __main__ import failed"
```

### Step 4 ⏳ — 代码审查（小周）

审查要点：
- [ ] A 批 5 个文件已全部删除（verify: `ls commands/` 只剩 pipeline.py）
- [ ] `command_utils.py` 已删除（verify: `ls ws_server/command_utils.py` → not found）
- [ ] `match_exclamation` + 规则注册已从 scenario_matcher.py 移除
- [ ] `_sm_handle_exclamation` + `_handle_server_query` 已从 main.py 移除
- [ ] `!` 命令路由段（L1596-1618）已从 main.py 移除
- [ ] `is_task = bool(mention_names) or content.startswith("!")` → `is_task = bool(mention_names)` 正确
- [ ] B 批: `_cmd_task_update` 已正确移入 `pipeline_engine.py`，调用处同步更新
- [ ] C 批: `commands/pipeline.py` 只保留了 step ops + 工具函数，无 ! pipeline handler 残留
- [ ] D 批: `workspace.py` / `workspace_api.py` 已删除
- [ ] D 批: `__main__.py` 中 workspace msg_type handler 已移除，不缺失其他路由端点
- [ ] D 批: `viewer.py` 中 workspace API 路由已移除，不影响其他 API
- [ ] D 批: `templates.py` 工作区 Tab 已移除，不影响其他 4 个 Tab
- [ ] E 批: `auto_router.py` 已删除
- [ ] **A12 确认: `_auto_dispatch` 中 `from_name` 已改为 "系统"，`agent_id` 已改为 `state.SYSTEM_AGENT_ID`**
- [ ] `py_compile` 全部通过
- [ ] `from server.ws_server import main` 无 ImportError

### Step 5 ⏳ — 测试验证（泰虾）

逐项验证验收标准（共 26 项，详见需求文档 §4）：

**CLN 组（12 项）：**
- CLN-1 ~ CLN-5: 5 个 ! 命令文件已删除
- CLN-6: `commands/pipeline.py` 已精简，无 ! handler 残留
- CLN-7: `commands/task.py` 已删除，`_cmd_task_update` 已迁移
- CLN-8 ~ CLN-10: main.py 中 3 个 ! 命令代码段已删除
- CLN-11: scenario_matcher.py 中 ! 命令规则已删除
- CLN-12: auto_router.py 已删除
- CLN-13: `_auto_dispatch` 发件人身份已修复（"系统" 而非 "小谷"）

**WKS 组（6 项）：**
- WKS-1 ~ WKS-2: workspace.py / workspace_api.py 已删除
- WKS-3: __main__.py handler 已清理
- WKS-4: main.py ws_mod 引用已清理
- WKS-5 ~ WKS-6: Web UI workspace Tab + API 已清理

**RV 组（8 项）：**
- RV-1 ~ RV-3: `##query` / `##step` / `##start` 命令正常工作
- RV-4: `_inbox:server` 收消息/派活/to_agent 正常
- RV-5 ~ RV-7: 编译 + 运行时导入零错误
- RV-8: Web UI 加载正常（📬 收件箱 / 📊 管线 Tab 可见）

### Step 6 ⏳ — 合并部署（小爱）

1. 合 `dev → main`
2. 部署到生产环境
3. `##status` 确认服务正常
4. 验证 Web UI（收件箱 + 管线 Tab 可见，工作区 Tab 消失）
5. 验证 `##query##whoami` / `##query##status` / `##step##complete##R134` 正常
6. 通知 PM 验收完成

---

## 改动预览

| 文件 | 操作 | 行数变化 | 说明 |
|:----|:----:|:--------:|:-----|
| `server/ws_server/commands/__init__.py` | ❌ 删除 | -202 | ! 命令注册表 |
| `server/ws_server/commands/workspace.py` | ❌ 删除 | -455 | !workspace 命令 |
| `server/ws_server/commands/admin.py` | ❌ 删除 | -176 | !admin 命令 |
| `server/ws_server/commands/agent_card.py` | ❌ 删除 | -258 | !agent_card 命令 |
| `server/ws_server/commands/task.py` | ❌ 删除 | -197 | !task 命令（_cmd_task_update 已迁移） |
| `server/ws_server/command_utils.py` | ❌ 删除 | -205 | 命令工具函数 |
| `server/ws_server/workspace.py` | ❌ 删除 | -460 | Workspace 核心 |
| `server/ws_server/workspace_api.py` | ❌ 删除 | -37 | Workspace API |
| `server/ws_server/auto_router.py` | ❌ 删除 | -750 | 已退役 AutoRouter |
| `server/ws_server/commands/pipeline.py` | 🔧 精简 | -885 | 删除 ! handler，保留 step ops |
| `server/ws_server/pipeline_engine.py` | 🔧 修改 | +~60 | 迁入 _cmd_task_update |
| `server/ws_server/main.py` | 🔧 清理 | -90 | 删除 3 个 ! 代码段 + ws_mod |
| `server/ws_server/__main__.py` | 🔧 清理 | -80 | 删除 workspace handler |
| `server/ws_server/scenario_matcher.py` | 🔧 清理 | -15 | 删除 match_exclamation |
| `server/web_ui/templates.py` | 🔧 清理 | -20 | 删除 📂 工作区 Tab |
| `server/web_ui/viewer.py` | 🔧 清理 | -20 | 删除 workspace API |
| **合计** | | **~-3,750 行** | **减负 ~22%** |
