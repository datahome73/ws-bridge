# R93 产品需求 — 做减法 🧹

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-11
> **前置条件：** R92 AutoRouter 全信号路径闭环已部署 ✅（main `0333fef`）
> **改动范围：** `server/auth.py` / `server/persistence.py` / `server/handler.py` / `server/__main__.py` / `shared/protocol.py` 清理

---

## 0. 背景：自动化管线通车后的减法周

R92 终于实现了 **`!pipeline_start` → 全自动 6-Step 管线**，AutoRouter 全信号路径闭环。自动化跑通后，回头看之前留下的遗迹——那些「当时有用但已被替代」的代码——正好清理干净。

**核心理念：项目负责人确认的设计方向**

> 「不再建角色等级体系（L4/L3/L2），让服务端自动化取代人工权限管理。R72 统一注册后 6 bot 地位平等，等级体系已过时。」

---

## 1. 🅰️ L1-L4 等级体系 — 删除

### 1.1 现状

`auth.py:81-105` 定义了完整的 L1-L4 等级体系：

```python
# ── R6: Role Level System
def role_level(agent_id: str) -> int:
    """Return role level: 4=global_admin, 3=workspace_admin, 2=member, 1=observer."""
    users = get_users()
    user = users.get(agent_id, {})
    if user.get("role") == "admin":
        return 4
    return 2  # All authenticated agents default to L2 member
```

### 1.2 问题

| 编号 | 问题 | 严重度 |
|:----:|:-----|:------:|
| 🅰️-1 | **`role_level()` 零调用者** — grep 整个 server/ 目录，0 处 import 或调用 | 🔴 |
| 🅰️-2 | **L1 和 L3 从未被返回** — 函数只返回 4 或 2，observer/L3 只活在 docstring 里 | 🟡 |
| 🅰️-3 | **实际权限检查用 `is_global_admin()`** — 一个简单 boolean 函数，不需要等级体系 | 🟢 |
| 🅰️-4 | **handler.py 中 "L2 member" / "L4 global admin" 注释** — 纯文档噪声，不影响逻辑 | 🟢 |

**根因：** R6 时代设计了等级体系，但后来实际实现中只使用 admin/member 二元区分（通过 `is_global_admin()`）。等级体系的 4 个级别从未被代码实际检查。`role_level()` 函数成为孤立代码。

### 1.3 方案

**删除 `role_level()` 函数** — 彻底的 dead code removal。

**不变：** `is_global_admin()` / `is_approved()` / `get_users()` / `get_agent_name()` 全部保留——这些仍在多个地方使用。

**改动：**

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/auth.py` | 删除 `role_level()` 函数和 R6 注释 | -8 |
| `server/handler.py` | 删除 7 处 "L2 member" / "L4 global admin" 注释 | -7 |
| **合计** | | **-15 行** |

---

## 2. 🅱️ 配对码系统 — 删除

### 2.1 现状

R6 时代的配对码（pairing code）审批系统，在 `auth.py` 中有全套实现：生成配对码、审批、过期清理。

```python
# auth.py
PAIRING_CODE_TTL = 300        # 5分锺
def generate_code() -> str    # 生成 8 位随机码
def create_pairing_code(...)  # 存储配对码
def approve(code, role)       # 审批配对码 → 加入 approved_users
def cleanup_expired_codes()   # 每 60s 清理过期码
```

配套代码分布在 5 个文件：

| 文件 | 内容 | 行数 |
|:-----|:-----|:----:|
| `server/auth.py:10-65` | 配对码生成/审批/清理函数 | ~55 |
| `server/persistence.py:10,33-61` | `_pairing_codes` 存储/加载/保存 | ~28 |
| `server/handler.py:485-498` | `handle_approve()` WebSocket 审批处理器 | ~14 |
| `server/handler.py:876-888` | `_cmd_approve_pairing` `!` 命令 | ~12 |
| `server/handler.py:346` | approve 提示代码 | ~3 |
| `server/handler.py:4741-4743` | 命令注册表条目 | ~3 |
| `server/__main__.py:18,21,51-54,797` | 启动加载 + 定期清理 | ~8 |
| `shared/protocol.py:22` | `MSG_PAIRING_CODE` 常量已标 DEPRECATED | ~1 |
| **合计** | | **~110+ 行**

### 2.2 问题

| 编号 | 问题 | 严重度 |
|:----:|:-----|:------:|
| 🅱️-1 | **R72 API Key 已全面替代** — 现在bot通过 `register` 协议自助注册，不需要 admin 审批配对码 | 🔴 |
| 🅱️-2 | **每 60s 运行 `cleanup_expired_codes()`** — 多余的定时循环 | 🟡 |
| 🅱️-3 | **每次启动加载 `_pairing_codes.json`** — 该文件可能为空或不存在 | 🟢 |
| 🅱️-4 | **`protocol.py` 已标 DEPRECATED** — 官方承认的废弃代码 | 🟢 |

**根因：** R72（api_key 注册体系）后，配对码系统已完全退役。但代码从未清理。`protocol.py` 中 `MSG_PAIRING_CODE` 已标 DEPRECATED，但配套代码一直保留。

### 2.3 方案

**删除整个配对码系统。** 包括：

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/auth.py` | 删除 `generate_code()`, `create_pairing_code()`, `approve()`, `cleanup_expired_codes()`, `PAIRING_CODE_TTL`, `_code_expired()` | -50 |
| `server/persistence.py` | 删除 `_pairing_codes`, `load_pairing_codes()`, `save_pairing_codes()`, `get_pairing_codes()`, `set_pairing_codes()` | -28 |
| `server/handler.py` | 删除 `handle_approve()` 函数 | -14 |
| `server/handler.py` | 删除 `_cmd_approve_pairing()` 函数 + 注册表条目 | -15 |
| `server/handler.py` | 删除 approve 提示代码 | -3 |
| `server/__main__.py` | 删除 `load_pairing_codes`, `save_pairing_codes` import + 调用 + 清理循环 | -8 |
| `shared/protocol.py` | 删除 `MSG_PAIRING_CODE`, `PAIRING_CODE_TTL` | -2 |
| `server/handler.py` | 命令注册表 `"approve_pairing"` 条目 | -5 |
| **合计** | | **~-125 行** |

**注意：** `approved_users` 系统（`persistence.py` 中的 `_approved_users` / `get_approved_users()` / `set_approved_users()` / `load_approved_users()` / `save_approved_users()`）**保留不动**——`is_global_admin()` 和 `is_approved()` 仍依赖它。

---

## 3. 🅲 R63 Feature Toggles — 清理

### 3.1 现状

R63 时期引入了 3 个 feature toggle 环境变量，默认均为 `"1"`（启用）：

```python
# handler.py:86-88
_ENABLE_R63_TIMEOUT: bool = os.environ.get("R63_ENABLE_TIMEOUT", "1") == "1"
_ENABLE_R63_AGENT_MAP: bool = os.environ.get("R63_ENABLE_AGENT_MAP", "1") == "1"
_ENABLE_R63_ACK: bool = os.environ.get("R63_ENABLE_ACK", "1") == "1"
```

### 3.2 问题

| 编号 | 问题 | 严重度 |
|:----:|:-----|:------:|
| 🅲-1 | **`_ENABLE_R63_AGENT_MAP` 零读取** — 定义后从未在任何 `if` 判断中使用 | 🔴 |
| 🅲-2 | **`config.py` 对应变量也从无人读取** — handler.py 用自己的副本 | 🟢 |
| 🅲-3 | **`_ENABLE_R63_TIMEOUT` / `_ENABLE_R63_ACK` 永远为真** — 生产从未设过 "0" | 🟡 |
| 🅲-4 | **每次 handler 初始化都 os.environ.get 一次** — 不影响性能但冗余 | 🟢 |

**根因：** R63 引入了 feature toggle 作为安全上线机制。R63 之后所有功能已稳定，从未需要禁用。`_ENABLE_R63_AGENT_MAP` 可能在开发阶段有用但后来删除了所有检查点。

### 3.3 方案

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` | 删除 `_ENABLE_R63_AGENT_MAP` 定义 | -2 |
| `server/handler.py` | `_ENABLE_R63_TIMEOUT`：4 处 if 判断直接移除| -4 |
| `server/handler.py` | `_ENABLE_R63_ACK`：2 处 if 判断直接移除 | -2 |
| `server/config.py` | 删除 `R63_ENABLE_*` 3 个配置项 | -3 |
| **合计** | | **-11 行** |

**验证（`_ENABLE_R63_TIMEOUT` 使用点）：**

| 位置 | 代码 | 删除方式 |
|:----:|:-----|:---------|
| handler.py:1819 | `if _ENABLE_R63_TIMEOUT:` → 移除 if，保留内部代码 | `_task_timeout = int(params.get("timeout", 7200))` |
| handler.py:1863 | `if _ENABLE_R63_TIMEOUT:` → 同上 | 移除 if 守卫 |
| handler.py:3536 | `if _ENABLE_R63_TIMEOUT:` → 同上 | 移除 if 守卫 |
| handler.py:4355 | `if current and _ENABLE_R63_TIMEOUT:` → 移除后半 | `if current:` |

---

## 4. 🅳 MSG_REGISTER_AGENT 旧路径 — 删除

### 4.1 现状

handler.py:7039-7070 有一段完整的 `MSG_REGISTER_AGENT` 处理路径，注释写明 **「DEPRECATED — R72 新体系使用 register 协议」**。

```python
elif msg_type == p.MSG_REGISTER_AGENT and agent_id:
    # DEPRECATED — R72 新体系使用 register 协议，旧 R23 路径保留不动
    # 仅 admin 可执行（R23 遗留路径）
    # 通过 _approved_users 注册
    ...
```

### 4.2 问题

| 编号 | 问题 | 严重度 |
|:----:|:-----|:------:|
| 🅳-1 | **已标注 DEPRECATED 但代码保留** — 自己承认废弃 | 🔴 |
| 🅳-2 | **～30 行代码 + 注释** — 含审批逻辑、连接通知、权限检查 | 🟡 |
| 🅳-3 | **R72 `register` 协议是唯一在用的注册路径** | 🟢 |

### 4.3 方案

**直接删除 MSG_REGISTER_AGENT 处理分支**。

- 不影响现有 R72 注册流程
- 不影响 handler.py 其他部分
- 删除约 ~30 行代码

---

## 5. 改动总结

### 5.1 净行数预估

| 类别 | 文件 | 删除行 | 新增行 | 净变化 |
|:-----|:-----|:------:|:------:|:------:|
| 🅰️ 等级体系 | auth.py / handler.py | -15 | 0 | **-15** |
| 🅱️ 配对码系统 | auth.py / persistence.py / handler.py / __main__.py / protocol.py | -125 | 0 | **-125** |
| 🅲 R63 toggles | handler.py / config.py | -11 | 0 | **-11** |
| 🅳 旧注册路径 | handler.py | -30 | 0 | **-30** |
| **合计** | **5+ 文件** | **-181** | **0** | **-181** |

### 5.2 零功能影响

| 场景 | 影响 | 说明 |
|:-----|:-----|:------|
| 新 bot API key 注册 | ✅ 无 | 走 R72 register 协议，不受影响 |
| 已注册 bot 发送消息 | ✅ 无 | 路由/权限/认证不受影响 |
| `!pipeline_start` 管线启动 | ✅ 无 | AutoRouter 流程不变 |
| `!` 命令 (workspace 等) | ✅ 无 | 命令注册表只移除 approve_pairing |
| 存量 `_pairing_codes.json` 文件 | ✅ 无 | 不再加载，文件可安全删除 |
| `_admin` / inbox 频道 | ✅ 无 | 路由逻辑不受影响 |
| `is_approved()` / `is_global_admin()` | ✅ 无 | approved_users 保留不动 |
| manual mode 角色检查 (line 3169) | ✅ 无 | 当前逻辑已 buggy，保持不动单独评估 |
| 测试 | ✅ 无 | 无测试文件覆盖已删除代码（0 测试引用） |

### 5.3 四个删除的共同特点

所有四个删除项的共同特征：

1. ✅ **零调用者** — grep 确认无 import / 引用 / 执行路径
2. ✅ **已被替代** — R72 API Keys / Agent Cards / AutoRouter 等新功能已覆盖
3. ✅ **代码自认废弃** — 有 DEPRECATED 注释或文档说明
4. ✅ **零回归风险** — 删除后不影响任何现有功能

---

## 6. R93 管线 Step 定义

```
Step 1: PM — 该需求文档 + WORK_PLAN → 推 dev
Step 2: Arch — 技术方案（确认 4 项删除的安全范围 + 异常情况）
Step 3: Dev — 编码清理（纯删除，零新增行）
Step 4: Review — 代码审查（重点确认无功能回归）
Step 5: QA — 测试验证（回归测试 + 确认 4 项删除无害）
Step 6: Ops — 合并部署
```

---

## 7. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| 🅰️-1 | `role_level()` 已从 auth.py 删除 | grep 确认零残留 |
| 🅰️-2 | handler.py 中 L2/L4 注释已清理 | grep 确认零残留 |
| 🅱️-1 | 配对码函数从 auth.py 完全删除 | grep "generate_code\|approve(" 零残留 |
| 🅱️-2 | persistence.py 配对码存储函数已删除 | grep "pairing_codes" 零残留 |
| 🅱️-3 | handler.py `handle_approve()` / `_cmd_approve_pairing()` 已删除 | grep 确认 |
| 🅱️-4 | `__main__.py` 配对码加载/保存/清理已删除 | grep 确认 |
| 🅱️-5 | `protocol.py` `MSG_PAIRING_CODE` / `PAIRING_CODE_TTL` 已删除 | grep 确认 |
| 🅲-1 | `_ENABLE_R63_AGENT_MAP` 已删除 | grep 确认 |
| 🅲-2 | `_ENABLE_R63_TIMEOUT` / `_ENABLE_R63_ACK` 守卫已简化 | 4+2 处 if 移除 |
| 🅲-3 | `config.py` R63_ENABLE 配置项已删除 | grep 确认 |
| 🅳-1 | `MSG_REGISTER_AGENT` 处理分支已删除 | grep 确认 |
| ✅ | 总行数验证：删除 ≥ 180 行、新增 0 行 | `git diff --stat` |
| ✅ | 回归测试全部通过 | `python3 -m pytest tests/` |
| ✅ | 存量 bot 认证不受影响（R72 api_key） | 用 api_key 连接验证 auth OK |
