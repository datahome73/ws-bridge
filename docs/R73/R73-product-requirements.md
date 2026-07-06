# R73 产品需求 — R72 认证体系修复 & 全员迁移 🎯

> 版本：v1.0（初稿，待审核）
> 状态：📝 草稿
> 日期：2026-07-06
> 本轮改动范围：仅 `server/` + `docs/`
> 参考：R72 部署完成(2026-07-06, b21e720)

---

## 1. 问题背景

### 1.1 现状

R72 新认证体系（`register` → `api_key` → `Agent Card 自注册`）已于 2026-07-06 部署上线，旧 `agent_id + app_id + pairing_code` 认证已下线。全员 6 bot 已在新体系下完成注册 + Agent Card 注册。

但经实际验证，存在**以下 5 个 bug**：

| # | Bug | 严重度 | 状态 |
|:-:|:----|:-----:|:----:|
| B1 | 新注册 agent 不在 `_approved_users`，无法执行 admin 命令 | 🔴 P0 | 未修 |
| B2 | `handle_auth` 不更新 Agent Card 的 `last_online`/`status` | 🔴 P0 | ✅ 代码已推 `dev` |
| B3 | `_build_online_list` 过滤掉 R72 注册 agent → 点名时不显示 | 🟡 P1 | ✅ 代码已推 `dev` |
| B4 | `REGISTRATION-GUIDE.md` `agent_card_register` 字段错误 | 🟡 P1 | ✅ 文档已推 `dev` |
| B5 | 旧 `credentials.json`(`/opt/data/.ws-bridge/`) 与新 `~/.ws-bridge/{name}.json` 并存 | 🟢 P2 | 未修 |
| B6 | 小爱角色名：`admin` → `operations`（R73 全员迁移时体现） | 🟡 P1 | 未修 |

### 1.2 根因分析

| # | 根因 | 涉及文件 |
|:-:|:-----|:---------|
| B1 | R72 的 `handle_register` 只写 `_api_keys.json`，不写 `_approved_users.json`。旧权限检查（`auth.get_users()` → `persistence.get_approved_users()`）不包含新 agent | `auth.py`, `persistence.py`, `handler.py` |
| B2 | `handle_auth` 认证成功后不更新 Agent Card 的 `last_online`/`status`。5min 后 `mark_stale_offline(300)` 标记为 offline 后无法恢复 | `handler.py:handle_auth` |
| B3 | `_build_online_list` 通过 `if aid in users` 过滤，R72 agent 不在 `users`（approved_users） | `handler.py:_build_online_list` |
| B4 | 文档示例使用 `trigger_preferences.mention_keyword` 但服务端期望顶层 `trigger_keyword` | `docs/R72/REGISTRATION-GUIDE.md` |
| B5 | R72 新脚本将凭证存到 `~/.ws-bridge/` 但旧路径 `/opt/data/.ws-bridge/credentials.json` 未删除 | 无代码改动 |
| B6 | R73 规划中已明确小爱角色从 `admin` 改为 `operations` | `handler.py:handle_register` |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:----|:------|
| 🔴 **R72 核心流程断裂** | 新 agent 注册后无法查看 Agent Card 列表、无法查管线状态、无法用 rollcall — 等于认证了但没有操作权限 |
| 🔴 **离线状态无法恢复** | Agent 重新连接后卡仍显示 offline，Web UI 上永远 🔴 |
| 🟡 **点名不显示 R72 agent** | 用户发 📋 点名，R72 注册的 agent 不在列表中，造成未注册的错觉 |
| 🟡 **文档错误引后续使用者** | `REGISTRATION-GUIDE.md` 的示例字段与实现不匹配，后续注册会重复踩坑 |
| 🟢 **冗余文件影响观感** | 旧 credentials.json 产生歧义 |

---

## 2. 功能需求

### 设计原则

> **本轮的核心理念：** R72 上线了「注册→认证」这条新路径，但旧权限墙（`_approved_users`）没有打通。R73 的目标是在认证体系内部补全权限链路，**让 R72 注册的 agent 和旧 agent 在权限上平权**。
>
> 不改 `_approved_users` 本身（旧体系路径不动），而是让 R72 注册的 agent 在权限检查时自动被识别为已认证 agent，无需手工加白名单。
>
> 具体方案：在 `auth.validate_api_key()` 返回的 agent_id 基础上，构建一个「R72 注册 agent 也视为有效用户」的权限查询链。**不需要增删 `_approved_users.json`**。

---

### 方向 A（核心）：R72 注册 agent 权限打通 🔴 P0

**问题：** 所有 admin 命令（`!agent_card list`, `!pipeline_status`, `!agent_role_map`, `!rollcall`, `📋` 点名等）在入口处调用 `auth.role_level(agent_id)`，而 `role_level` 调用 `auth.get_users()` → `persistence.get_approved_users()`，新注册 agent 不在其中 → 返回 `role_level = None` → 权限不足。

**思路：** 不要改 `_approved_users` 的逻辑，而是让 `auth.is_approved_user()` / `auth.get_users()` / `auth.role_level()` 在返回空结果时，**fallback 到 `persistence.get_api_keys()`** 检查。如果 api_keys 中有该 agent_id → 视为已认证用户（`role_level = 2`, `role = "member"`）。

#### A1 — `auth.is_approved_user()` 补充 api_key 检查

**位置：** `server/auth.py`

```python
# 当前代码
def is_approved_user(agent_id: str) -> bool:
    return agent_id in get_users()

# → 改造后
def is_approved_user(agent_id: str) -> bool:
    if agent_id in get_users():
        return True
    # R73: 也检查 R72 api_key 注册的 agent
    api_keys = persistence.get_api_keys()
    return agent_id in api_keys
```

#### A2 — `auth.role_level()` 对 api_key agent 返回默认 L2

**位置：** `server/auth.py`

```python
# 当前代码
def role_level(agent_id: str) -> int:
    users = get_users()
    user = users.get(agent_id, {})
    if user.get("role") == "admin":
        return 4
    return 2

# → 改造后（无需改——已注册 agent 默认 L2 member）
# 但需要确保用户在 get_users() 找不到时不会返回 None 导致权限检查误判
```

实际上 `role_level` 已经对未找到的用户返回 `2`（member），所以 A2 只需要 A1 修改 `is_approved_user` 即可——所有依赖 `is_approved_user` 的 admin 命令会新检测到 api_key 注册的 agent。

#### A3 — 各处权限检查入口确认

需 grep 确认以下命令/函数入口使用了 `is_approved_user` 或 `role_level`：

| 检查点 | 当前 | 预期 |
|:-------|:----|:-----|
| `_cmd_agent_card_list` | `min_role: 3` | API Key agent 有 role_level=2，仍无权——需要额外处理 |
| `!pipeline_status` | 不限 admin | ✅ 应已可用 |
| `_build_online_list` | ✅ 已修（代码已推 dev） | — |

> **注意：** `_ADMIN_COMMANDS` 中大部分命令的 `min_role: 3` 意味着 workspace_admin 或 global_admin 才能执行。R72 agent 默认 role_level=2 是 member，所以 `!agent_card list` 等仍无权。**需要决定：是降级 min_role 为 2（member 可执行），还是修改 `role_level` 对 api_key agent 返回更高级别？**

**方案：** `!agent_card list` 和 `!agent_card get` 的 `min_role` 降级为 `2`（member 级别可查看），`set/unset` 保持 `3`。这样 R72 agent 可查卡片但不能改。

#### A4 — 后向兼容：旧 agent 仍可正常使用

无需改动——`is_approved_user` 仍先检查旧 `_approved_users`，再 fallback 到 api_keys。旧 agent 行为完全不变。

### 方向 B（辅助）：离线状态恢复 🔴 P0

**现状：** R72 注册时 `register_from_agent` 设置 `status: "online"`, `last_online: now`。5 分钟后 `mark_stale_offline(300)` 标记为 offline。此后 agent 重连（auth）时不更新 card → 永远 offline。

**修复代码已推 dev**（`9f353a9`），包含：
- B1: `handle_auth` → 调用 `_update_agent_online_status(agent_id)` 更新 card
- B2: `handle_register` → 同上
- B3: `_build_online_list` → 也查询 api_keys / Agent Card

**本轮仅验证：** 部署后重新认证，确认 `!agent_card list` 显示 `status=online`。

### 方向 C（微调）：小爱角色 admin → operations 🟡 P1

R73 规划中明确：小爱角色名从 `admin` 改为 `operations`。

| 修改点 | 位置 | 改前 | 改后 |
|:-------|:-----|:-----|:-----|
| REGISTRATION-GUIDE.md | `docs/R72/REGISTRATION-GUIDE.md` §四 角色对照表 | `admin` | `operations` |
| 技能名 | 同上 | `运维管理,部署管理,系统监控` | 不变 |

> **说明：** 角色名 `pipeline_roles` 值仅影响管线角色映射展示，不改任何权限逻辑。小爱在服务端的权限不受影响。

### 方向 D（清理）：旧 credentials.json 移除 🟢 P2

`/opt/data/.ws-bridge/credentials.json`（旧 小谷凭证）在 R72 第二次注册后已过期。清理掉避免混淆。

---

## 3. 验收标准

### 🎯 3.1 方向 A：权限打通

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | R72 新注册 agent 可执行 `!agent_card list` | 返回 Agent Card 列表，不报「权限不足」 | 用 小谷 api_key 连接，发 `!agent_card list` |
| ✅-2 | R72 新注册 agent 可执行 `!agent_role_map` | 返回角色映射表 | 同上，发 `!agent_role_map` |
| ✅-3 | R72 新注册 agent 可执行 `!pipeline_status` | 返回管线状态 | 同上，发 `!pipeline_status` |
| ✅-4 | 旧 agent（如果有）不受影响 | 旧 agent 原有权限不变 | 旧 agent 仍可执行原命令 |
| ✅-5 | R72 agent 无法执行 `!agent_card set` 等写操作 | 权限不足 | 发 `!agent_card set` → 被拒绝 |

### 🎯 3.2 方向 B：离线状态恢复

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-6 | agent auth 后 card 状态为 online | `status=online` | auth → `!agent_card get <agent_id>` |
| ✅-7 | agent auth 后 last_online 为当前时间 | last_online 刷新 | auth 前后对比 |

### 🎯 3.3 方向 C：小爱角色 operations

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-8 | REGISTRATION-GUIDE.md 小爱角色为 `operations` | `pipeline_roles: ["operations"]` | grep 文档 |
| ✅-9 | 小爱重新注册后 roles 为 `operations` | Agent Card 显示 roles=`operations` | 重新注册后查 card |

### 🎯 3.4 方向 D：清理

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-10 | `/opt/data/.ws-bridge/credentials.json` 移除 | 文件不存在 | `ls` 确认 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 持久连接守护脚本 | 保持 6 agent 在线的心跳守护 | 用户明确说「客户端改进，放到下一轮次」 |
| Role-level RBAC 完整体系 | 细粒度权限声明（P3 规划） | 架构路线中 P2，非本轮方向 |
| `_approved_users.json` 格式改造 | 把 api_key 信息合并进 approved_users | 最小改动原则——只加 fallback 检查 |
| 旧认证体系残留代码 | `pairing_code`, `approve` 等旧路径 | R72 已下线旧路径，代码清理留到后续 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现（~30 行净改） | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告（5 项验收） | 15min |
| **6** | 🛠️ Admin | 合并部署 + 全员重新注册 | 20min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/auth.py` | **修改** — `is_approved_user()` 增加 api_key fallback | ~3 行 |
| `server/handler.py` | **修改** — `_ADMIN_COMMANDS` 中 `agent_card list/get` 的 min_role 降级为 2 | ~2 行 |
| `docs/R72/REGISTRATION-GUIDE.md` | **修改** — 小爱角色 `admin` → `operations` | ~1 行 |
| `/opt/data/.ws-bridge/credentials.json` | **删除** — 旧凭证文件 | 删除 |
| **合计** | | **~6 行净改** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:-----|
| `is_approved_user` 增加 api_key fallback 后，旧权限路径不受影响 | 无 | 旧路径逻辑完全不改，只加 fallback |
| `min_role` 降级后 member 可查看 agent_card，无安全风险 | 低 | 查看操作不产生副作用 |
| 部署后需全体验证 | 节点 5 可控 | PM 逐个验证 5 项验收标准 |

---

## 6. 脱敏检查清单

- [ ] docs/R73/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R73/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / admin）
- [ ] 不包含真实 agent_id / token / URL
