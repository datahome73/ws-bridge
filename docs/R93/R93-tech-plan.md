# R93 技术方案 — 做减法 🧹

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求：** `docs/R93/R93-product-requirements.md` v1.0
> **前置条件：** R92 AutoRouter 全信号路径闭环已部署 ✅ (main `0333fef`)
> **改动文件：** `server/auth.py` / `server/persistence.py` / `server/handler.py` / `server/__main__.py` / `shared/protocol.py` / `server/config.py`
> **总行数：** 纯删除 ~-181 行 · 零新增 ✅

---

## 目录

1. [验证方法：四步安全删除法](#1-验证方法四步安全删除法)
2. [🅰️ L1-L4 等级体系 — `role_level()` 删除](#️-l1-l4-等级体系--role_level-删除)
3. [🅱️ 配对码系统 — 5 文件删除](#️-配对码系统--5-文件删除)
4. [🅲 R63 Feature Toggles — 3 变量赋值 + 6 处守卫移除](#️-r63-feature-toggles--3-变量赋值--6-处守卫移除)
5. [🅳 MSG_REGISTER_AGENT 旧路径 — handler.py 分支删除](#️-msg_register_agent-旧路径--handlerpy-分支删除)
6. [改动总览表](#6-改动总览表)
7. [风险与边界检查](#7-风险与边界检查)
8. [编码预检表](#8-编码预检表)
9. [验收清单](#9-验收清单)

---

## 1. 验证方法：四步安全删除法

每一类清理都遵循以下四步：

| 步骤 | 操作 | 验证 |
|:----:|:-----|:-----|
| ① grep 基线 | `grep -rn <func_name> server/` 统计引用数 | 基线数字确保删除后归零 |
| ② 删除定义 | 删除函数/变量定义 | — |
| ③ grep 零残留 | 再次 `grep -rn <func_name> server/` | 返回 0 |
| ④ import 清理 | 检查 import 行是否因删除而变空 | 移除孤立 import |

**⚠️ 特别警告：** 配对码系统跨 5 文件，grep 必须覆盖全部文件（`server/` + `shared/`），且要 grep 每个被删函数名（而非只用一个大词 grep "pairing"）。

---

## 2. 🅰️ L1-L4 等级体系 — `role_level()` 删除

### 2.1 改动坐标

| # | 文件 | 内容 | 删除方式 |
|:-:|:-----|:-----|:---------|
| A-1 | `server/auth.py` L80-L105 | `role_level()` 函数定义 + `# ── R6: Role Level System` 注释 | 整块删除 |
| A-2 | `server/handler.py` 全文件 | 7 处 `L2 member` / `L4 global admin` 纯注释 | 逐行删除 |

### 2.2 A-1 删除范围 (auth.py)

```python
# ── R6: Role Level System  ← 删整段
def role_level(agent_id: str) -> int:
    """Return role level: 4=global_admin, 3=workspace_admin, 2=member, 1=observer."""
    users = get_users()
    user = users.get(agent_id, {})
    if user.get("role") == "admin":
        return 4
    return 2
```

**验证：** `grep -rn "role_level" server/auth.py` → 0 匹配

### 2.3 A-2 删除范围 (handler.py)

`grep -n "L2\|L4.*global\|等级" server/handler.py` 定位所有纯注释行，确认不在代码逻辑中。

---

## 3. 🅱️ 配对码系统 — 5 文件删除

### 3.1 改动总览

| # | 文件 | 删除内容 | 预估行数 |
|:-:|:-----|:---------|:--------:|
| B-1 | `server/auth.py:10-65` | `PAIRING_CODE_TTL`, `generate_code()`, `create_pairing_code()`, `approve()`, `cleanup_expired_codes()`, `_code_expired()` | -55 |
| B-2 | `server/persistence.py:10,33-61` | `_pairing_codes` 变量 + `load_pairing_codes()`, `save_pairing_codes()`, `get_pairing_codes()`, `set_pairing_codes()` | -28 |
| B-3 | `server/handler.py` | `handle_approve()` 函数 + `_cmd_approve_pairing()` 函数 | -29 |
| B-4 | `server/handler.py` | 命令注册表 `"approve_pairing"` 条目 + approve 提示代码 | -8 |
| B-5 | `server/__main__.py` | `load_pairing_codes` / `save_pairing_codes` import + 调用 + 清理循环 | -8 |
| B-6 | `shared/protocol.py` | `MSG_PAIRING_CODE`, `PAIRING_CODE_TTL` | -2 |
| **合计** | | | **~-125** |

### 3.2 精确坐标

#### B-1: auth.py 配对码函数

`grep -n "def generate_code\|def create_pairing_code\|def approve\b\|def cleanup_expired\|def _code_expired\|PAIRING_CODE_TTL" server/auth.py`

删除后检查：`grep -n "pairing\|PAIRING\|generate_code\|approve(" server/auth.py` → 0 匹配

**⚠️ 注意：** `is_approved()` / `is_global_admin()` **不能删** — 它们依赖 `_approved_users` 系统，配对码的 `approve()` 只是写入 `_approved_users` 的路径之一。

#### B-2: persistence.py 配对码存储

`grep -n "_pairing_codes\|def load_pairing\|def save_pairing\|def get_pairing\|def set_pairing" server/persistence.py`

删除后检查：`grep -n "pairing" server/persistence.py` → 0 匹配

#### B-3: handler.py handle_approve + _cmd_approve_pairing

```python
# ── R23: WS approve handler — 配对码审批 (DEPRECATED R72)
async def handle_approve(ws, msg_data):
    ...
```

以及：

```python
# ── R6: Approve pairing code
async def _cmd_approve_pairing(...):
    ...
```

**删除后验证：**
```bash
grep -n "def handle_approve\|def _cmd_approve_pairing" server/handler.py  # → 0
grep -n "pairing\|approve_code\|approve_pairing" server/handler.py      # → 0（命令注册表已清理）
```

#### B-4: handler.py 命令注册表

在 `_ADMIN_COMMANDS` dict 中找到 `"approve_pairing"` 条目，整行删除。

#### B-5: __main__.py

```python
from persistence import load_pairing_codes, save_pairing_codes  # ← 删

# main() 中
await persistence.load_pairing_codes()        # ← 删
await persistence.save_pairing_codes()         # ← 删（如有）
asyncio.create_task(pairing_code_cleanup())    # ← 删
```

#### B-6: protocol.py

```python
MSG_PAIRING_CODE = "pairing_code"          # ← 删（DEPRECATED 注释也删）
PAIRING_CODE_TTL = 300                     # ← 删
```

---

## 4. 🅲 R63 Feature Toggles — 3 变量赋值 + 6 处守卫移除

### 4.1 改动坐标

| # | 文件 | 内容 | 操作 |
|:-:|:-----|:-----|:-----|
| C-1 | `server/handler.py` L86-88 | `_ENABLE_R63_*` 3 个变量定义 | 删除整行 |
| C-2 | `server/handler.py` L1819 | `if _ENABLE_R63_TIMEOUT:` | 移除 if 守卫，保留内部 `_task_timeout = ...` |
| C-3 | `server/handler.py` L1863 | `if _ENABLE_R63_TIMEOUT:` | 同上 |
| C-4 | `server/handler.py` L3536 | `if _ENABLE_R63_TIMEOUT:` | 同上 |
| C-5 | `server/handler.py` L4355 | `if current and _ENABLE_R63_TIMEOUT:` | 改为 `if current:` |
| C-6 | `server/handler.py` | `if _ENABLE_R63_ACK:` 2 处 | 移除 if 守卫，保留内部代码 |
| C-7 | `server/config.py` | `R63_ENABLE_*` 3 个配置项 | 删除配置定义 |

### 4.2 精确坐标

**C-2 ~ C-5 模式（`_ENABLE_R63_TIMEOUT` 的 4 处 if）：**

```python
# 旧代码
if _ENABLE_R63_TIMEOUT:
    _task_timeout = int(params.get("timeout", 7200))

# 新代码（移除 if，直接保留赋值）
_task_timeout = int(params.get("timeout", 7200))
```

**⚠️ 注意：** 移除 if → 内部代码必须保持原格式对齐。验证：
```bash
grep -n "ENABLE_R63" server/handler.py  # → 0 匹配
grep -n "ENABLE_R63" server/config.py   # → 0 匹配
```

---

## 5. 🅳 MSG_REGISTER_AGENT 旧路径 — handler.py 分支删除

### 5.1 改动坐标

| # | 文件 | 行号范围 | 内容 |
|:-:|:-----|:--------:|:-----|
| D-1 | `server/handler.py` | ~L7039-7070 | `elif msg_type == p.MSG_REGISTER_AGENT and agent_id: ...` 整段删除 |

### 5.2 删除边界

从 `# DEPRECATED — R72 新体系使用 register 协议` 注释开始，到该 elif 分支的 `# end of MSG_REGISTER_AGENT` 或下一个 `elif` / 缩进返回处结束。

**确认 grep 基线：**
```bash
grep -n "MSG_REGISTER_AGENT" server/handler.py  # 记录当前位置
# 删除后检查
grep -n "MSG_REGISTER_AGENT" server/handler.py  # → 0
```

---

## 6. 改动总览表

| 类别 | 文件 | 删除行 | 净变化 |
|:-----|:-----|:------:|:------:|
| 🅰️ 等级体系 | auth.py + handler.py | -15 | **-15** |
| 🅱️ 配对码系统 | 5 文件 | -125 | **-125** |
| 🅲 R63 toggles | handler.py + config.py | -11 | **-11** |
| 🅳 旧注册路径 | handler.py | -30 | **-30** |
| **总计** | **6 文件** | **-181** | **-181** |

---

## 7. 风险与边界检查

### 7.1 双入口同步

| 检查项 | 🅱️ 配对码 | 🅳 注册路径 | 说明 |
|:-------|:---------:|:----------:|:-----|
| `handler.py` (websockets) | `handle_approve()` + `_cmd_approve_pairing()` | `MSG_REGISTER_AGENT` 分支 | 这些全在 handler.py·不在 `__main__.py` |
| `__main__.py` (aiohttp) | 仅配对码加载/保存/清理循环 | ❌ 没有 `MSG_REGISTER_AGENT` 分支 | 旧注册路径只在 websockets 入口 |

**结论：** 🟠 `__main__.py` 的配对码加载/保存/清理需在两边同步删除。`MSG_REGISTER_AGENT` 只在 handler.py 中有分支，无需双入口同步。

### 7.2 import 依赖检查

| 文件 | 删除后可能变空的 import | 处理 |
|:-----|:-----------------------|:-----|
| `persistence.py` | 删除 `_pairing_codes` 和配对码函数 — 检查 import | 无外部 import，安全 |
| `__main__.py` | `from persistence import load_pairing_codes, save_pairing_codes` | **必须删除** import 行，否则 NameError |

### 7.3 留存检查

**⚠️ 以下内容不应被删除（非本轮 scope）：**

| 内容 | 位置 | 原因 |
|:-----|:-----|:-----|
| `is_global_admin()` / `is_approved()` | auth.py | 仍在多处使用（命令权限检查） |
| `approved_users` / `load_approved_users()` / `save_approved_users()` | persistence.py | 全局管理员系统依赖它 |
| `handle_broadcast()` | handler.py | 核心消息路由 |
| `_parse_command()` / `_ADMIN_COMMANDS` 其他条目 | handler.py | 其他命令仍需使用 |
| 其他 `MSG_*` 常量 | protocol.py | 仅删 `MSG_PAIRING_CODE` |

---

## 8. 编码预检表

| 改动 | 文件 | 精确坐标 | 操作 | 预估行数 |
|:----|:-----|:--------:|:----:|:--------:|
| A-1 | `auth.py` | `role_level()` 定义行 | 删除函数+注释 | -8 |
| A-2 | `handler.py` | 7 处 L2/L4 注释行 | 逐行删除 | -7 |
| B-1 | `auth.py` | `generate_code` ~ `PAIRING_CODE_TTL` 块 | 整段删除 | -55 |
| B-2 | `persistence.py` | `_pairing_codes` + 4 个函数 | 删除 | -28 |
| B-3 | `handler.py` | `handle_approve()` 函数 | 删除 | -14 |
| B-3 | `handler.py` | `_cmd_approve_pairing()` 函数 | 删除 | -15 |
| B-4 | `handler.py` | `_ADMIN_COMMANDS["approve_pairing"]` | 删除 | -8 |
| B-5 | `__main__.py` | import + 调用 + `create_task(cleanup)` | 删除 | -8 |
| B-6 | `protocol.py` | `MSG_PAIRING_CODE`, `PAIRING_CODE_TTL` | 删除 | -2 |
| C-1 | `handler.py` | 3 个 `_ENABLE_R63_*` 定义 | 删除 | -3 |
| C-2~5 | `handler.py` | 4 处 `_ENABLE_R63_TIMEOUT` if | 移除守卫 | -4 |
| C-6 | `handler.py` | 2 处 `_ENABLE_R63_ACK` if | 移除守卫 | -2 |
| C-7 | `config.py` | 3 个 `R63_ENABLE_*` | 删除 | -3 |
| D-1 | `handler.py` | `MSG_REGISTER_AGENT` 分支 | 整段删除 | -30 |

---

## 9. 验收清单

| # | 内容 | 验证命令 | 预期 |
|:-:|:-----|:---------|:-----|
| ✅-1 | `role_level()` 已删除 | `grep -rn "role_level" server/auth.py` | 0 匹配 |
| ✅-2 | handler.py L2/L4 注释已清理 | `grep -n "L2 member\|L4 global" server/handler.py` | 0 匹配 |
| ✅-3 | auth.py 配对码函数已删除 | `grep -rn "generate_code\|create_pairing\|def approve\|cleanup_expired" server/auth.py` | 0 匹配 |
| ✅-4 | persistence.py 配对码已删除 | `grep -rn "pairing" server/persistence.py` | 0 匹配 |
| ✅-5 | handler.py pairing 关联已删除 | `grep -rn "def handle_approve\|def _cmd_approve_pairing\|approve_pairing" server/handler.py` | 0 匹配 |
| ✅-6 | __main__.py 配对码已删除 | `grep -n "pairing" server/__main__.py` | 0 匹配 |
| ✅-7 | protocol.py 配对码已删除 | `grep -n "PAIRING\|pairing" shared/protocol.py` | 0 匹配 |
| ✅-8 | `_ENABLE_R63_*` 已删除 | `grep -n "ENABLE_R63" server/handler.py server/config.py` | 0 匹配 |
| ✅-9 | `_ENABLE_R63_TIMEOUT` if 已移除 | `grep -n "ENABLE_R63" server/handler.py` | 0 匹配 |
| ✅-10 | `MSG_REGISTER_AGENT` 已删除 | `grep -n "MSG_REGISTER_AGENT" server/handler.py` | 0 匹配 |
| ✅-11 | 总删除行数 ≥ 180 | `git diff --stat HEAD~1..HEAD` | 净删除 ≥ 180 |
| ✅-12 | 编译检查通过 | `python3 -c "compile(open('server/handler.py').read(),'handler.py','exec');print('OK')"` | OK |

---

*技术方案编写: 🏗️ 架构师 · 2026-07-11*
