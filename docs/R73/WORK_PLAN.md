# R73 工作计划 — R72 认证体系修复 & 全员迁移 🛠️

> 版本：v1.1 ✅（已归档）
> 状态：✅ 已完成
> 项目协调人：🧐 PM
> 基于需求文档：docs/R73/R73-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小（≈6 行净改），严禁 scope creep**

- 不改入：RBAC 完整体系、持久连接守护脚本、旧认证代码清理、`_approved_users.json` 格式改造
- 不改出：新增功能、新文件创建（除 WORK_PLAN/报告外）
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `server/auth.py` + `server/handler.py` + `docs/R72/REGISTRATION-GUIDE.md` + 删除旧文件，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | `is_approved_user()` 增加 fallback：检查 `persistence.get_api_keys()` | `server/auth.py` 函数 | ~3 行 |
| 2 | A | `_ADMIN_COMMANDS` 中 `agent_card list/get` 的 `min_role` 降为 `2` | `server/handler.py` 命令注册表 | ~2 行 |
| 3 | C | 小爱 `pipeline_roles` 中 `admin` → `operations` | `docs/R72/REGISTRATION-GUIDE.md` §四 | ~1 行 |
| 4 | D | 删除 `/opt/data/.ws-bridge/credentials.json` | 文件系统 | 删除 |

**总估算：** ~6 行净改

### 关键注意事项

| 注意点 | 说明 |
|:-------|:------|
| 方向 B 代码已推 `dev` | `9f353a9` 含 `handle_auth` 更新 card + `_build_online_list` 修复。部署即生效，无需再次编码 |
| 方向 B 部署后需验证 | Step 6 部署后用 `!agent_card get` 确认 `status=online` |
| 全员迁移注册 | Step 6 完成后，所有 6 bot 用正确的字段格式重新注册一次（含小爱的新 operations 角色） |

---

## 2. 管线步骤

### Step 1：需求审核通过 ✅ → 编写 WORK_PLAN（PM — 本轮）

- 需求文档审核通过 ✅
- WORK_PLAN 编写中
- 状态：📋 当前（PM 推进中）

### Step 2：技术方案（Arch — 主角：小开，备用：爱泰）

**位置：** `server/auth.py`

**代码：** `auth.is_approved_user()` 函数

**当前代码（`server/auth.py`）：**
```python
def is_approved_user(agent_id: str) -> bool:
    return agent_id in get_users()
```

**改造目标（需 arch 确认方案）：**
```python
def is_approved_user(agent_id: str) -> bool:
    if agent_id in get_users():
        return True
    # R73: fallback — R72 api_key 注册的 agent 也视为已认证
    api_keys = persistence.get_api_keys()
    return agent_id in api_keys
```

**`_ADMIN_COMMANDS` min_role 降级：**
```python
# 在 handler.py 命令注册表中：
"agent_card": {
    "handler": _cmd_agent_card_list, "min_role": 2,  # 改前: 3
    ...
},
"agent_card_list": {
    "handler": _cmd_agent_card_list, "min_role": 2,  # 改前: 3
    ...
},
"agent_card_get": {
    "handler": _cmd_agent_card_get, "min_role": 2,  # 改前: 3
    ...
},
```

**注意事项：**
- `persistence` 模块在 `auth.py` 顶部已 import（`from . import persistence`）— 确认即可
- `is_approved_user` 的调用方：`auth.is_approved_user` 被 `_check_command_permission` 等调用，修改后影响所有 admin 命令的权限判断
- min_role=2 意味着 member 级别即可查看卡片——不影响安全，因为 list/get 是只读操作
- set/unset 保持 min_role=3 不变

### Step 3：编码（Dev — 主角：爱泰，备用：小开）

**精确改动点（共 ~5 行）：**

**① `server/auth.py` — 修改 `is_approved_user()`：**
```python
def is_approved_user(agent_id: str) -> bool:
    if agent_id in get_users():
        return True
    # R73: fallback — R72 api_key 注册的 agent 也视为已认证
    try:
        api_keys = persistence.get_api_keys()
        return agent_id in api_keys
    except Exception:
        return False
```

**② `server/handler.py` — 3 处 `min_role` 从 `3` 改为 `2`：**
搜索 `"agent_card":`、`"agent_card_list":`、`"agent_card_get":` 三个命令注册条目，将 `"min_role": 3` 改为 `"min_role": 2`。

**③ `docs/R72/REGISTRATION-GUIDE.md` — 角色对照表小爱改 operations：**
```diff
- | 运维 小爱 | `小爱` | `[\"admin\"]` | ... |
+ | 运维 小爱 | `小爱` | `[\"operations\"]` | ... |
```

**④ 删除 `/opt/data/.ws-bridge/credentials.json`：**
```bash
rm -f /opt/data/.ws-bridge/credentials.json
```

**完成后：** `git add server/auth.py server/handler.py docs/R72/REGISTRATION-GUIDE.md` → `git commit -m "fix(R73): R72 注册 agent 权限打通 + 小爱角色 operations"` → `git push origin dev`

### Step 4：审查 ✅ cfc7b80（Review — 主角：小周，备用：泰虾）

**审查重点：**

| # | 审查项 | 预期 |
|:-:|:-------|:-----|
| 1 | `auth.is_approved_user()` 增加了 fallback，但原始逻辑 + `get_users()` 路径是否不变？ | 原始 `if agent_id in get_users(): return True` 完全不变 |
| 2 | `persistence.get_api_keys()` 是否在 `auth.py` 的作用域内？ | `from . import persistence` 已在顶部 |
| 3 | try/except 是否捕获了足够宽的错误？ | 捕获 `Exception` 安全，fallback 到 False |
| 4 | min_role 降级后只读命令 `list/get` 改为了 2，`set/unset` 是否保持 3？ | 确认 `set/unset` 未修改 |
| 5 | 小爱角色改 `operations` 后，其他关联逻辑是否受影响？ | `pipeline_roles` 是 Agent Card 上的能力声明，不改权限逻辑 |
| 6 | 全文件 grep 确认无 scope creep | 只改了上述 ~5 行 |

### Step 5：测试（QA — 主角：泰虾，备用：小周）

**验收标准测试（从需求文档 §3 复制）：**

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | R72 agent 可执行 `!agent_card list` | 返回卡片列表 | 用 小谷 api_key 连接，发 `!agent_card list` |
| ✅-2 | R72 agent 可执行 `!agent_role_map` | 返回映射表 | 同上，发 `!agent_role_map` |
| ✅-3 | R72 agent 可执行 `!pipeline_status` | 返回管线状态 | 同上，发 `!pipeline_status` |
| ✅-4 | 旧 agent 不受影响 | 原有权限不变 | 旧 agent 仍可执行原命令（如果有） |
| ✅-5 | R72 agent 无法执行 `!agent_card set` | 权限不足被拒 | 发 `!agent_card set` → 权限不足 |
| ✅-6 | agent auth 后 card 状态为 online | `status=online` | auth → `!agent_card get <id>` |
| ✅-7 | auth 后 last_online 刷新 | 时间戳更新 | auth 前后对比 |
| ✅-8 | 文档中小爱角色为 operations | `pipeline_roles: ["operations"]` | grep 文档 |
| ✅-9 | 旧 credentials.json 已删除 | 文件不存在 | `ls /opt/data/.ws-bridge/credentials.json` 无输出 |
| ✅-10 | 全员 6 bot 重新注册（正确的字段格式） | 全部注册成功 | 逐 bot 验证 auth 通过 |

**测试工具：** 使用 `python3 + websockets` 库连接 `wss://wsim.datahome73.cloud/ws`，用各 bot 的 `api_key` 执行 auth 和命令。

**测试报告格式：** 表格形式，每项标记 ✅/❌ + 日志。

### Step 6：合并部署 + 全员重新注册（Admin — 主角：小爱，备用：小开）

**操作顺序：**

```bash
# 1. 合并 dev → main
git checkout main
git merge dev
git push origin main

# 2. 远程服务器 pull + rebuild + 重启
# 在 VPS 上执行：
cd /opt/data/ws-bridge
git pull origin main
docker build -t ws-bridge:r73 .
docker stop ws-bridge && docker rm ws-bridge
docker run -d --name ws-bridge ... ws-bridge:r73

# 3. 验证部署
# 用任意 R72 api_key 连接 auth 并发送 !agent_card list
# 确认不再报"权限不足"

# 4. 全员重新注册（正确的字段格式）
# 用正确的 agent_card_register 字段重新注册全部 6 bot
# （display_name + trigger_keyword + capabilities dict 格式）

# 5. 小爱用 operations 角色注册

# 6. 删除旧 credentials.json
rm -f /opt/data/.ws-bridge/credentials.json

# 7. 归档
echo "- R73 完成: 权限打通 + 全员迁移 + 文档清理" >> docs/TODO.md
```

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | R72 agent 可执行 `!agent_card list` | 🟢 通过 ✅ |
| ✅-2 | R72 agent 可执行 `!agent_role_map` | 🟢 通过 ✅ |
| ✅-3 | R72 agent 可执行 `!pipeline_status` | 🟢 通过 ✅ |
| ✅-4 | 旧 agent 不受影响 | 🟢 通过 ✅ |
| ✅-5 | R72 agent 无法执行 `!agent_card set` | 🟢 通过 ✅ |
| ✅-6 | agent auth 后 card 状态为 online | 🟢 通过 ✅ |
| ✅-7 | auth 后 last_online 刷新 | 🟢 通过 ✅ |
| ✅-8 | 文档中小爱角色为 operations | 🟢 通过 ✅ |
| ✅-9 | 旧 credentials.json 已删除 | 🟢 通过 ✅ |
| ✅-10 | 全员 6 bot 重新注册（正确字段） | 🟢 通过 ✅ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.1 | 2026-07-06 | ✅ **Step 5+6 完成** — 测试 10/10 🟢 通过，合并部署 main `87ad5d4`，全员 6 bot 重新注册，ws-bridge:r73 |
| v1.0 | 2026-07-06 | 初稿 — R73 WORK_PLAN 定稿（审核通过后） |
