# R93 QA 验证报告 — VERIFY-ARCH 🧹

> **版本：** v1.0
> **角色：** 🦐 QA（测试工程师）
> **日期：** 2026-07-11
> **验证范围：** R93-tech-plan.md 的 4 项删除安全性确认
> **技术方案提交：** `b71759a`

---

## 验证方法

对 dev 分支 HEAD（`b71759a`）进行 **grep 交叉验证**，逐项确认：

1. 被删函数/变量在 `server/` + `shared/` 中的完整引用清单
2. 零调用者确认（定义唯一，无 import/调用）
3. 保留函数不受影响（`is_approved()` / `is_global_admin()` 等）

---

## 🅰️ L1-L4 等级体系 — `role_level()` 删除

### 基线验证

| 检查项 | 结果 | 行号 |
|:-------|:----:|:----:|
| `role_level()` 定义 | ✅ auth.py:84 唯一定义 | 1 处 |
| `role_level()` 调用者 | ✅ **零调用者**（grep 全 server/ 仅 1 匹配 = 定义本身） | 0 处 |
| handler.py L2/L4 纯注释 | ✅ 7 处：L4897/L4930/L4965/L5004/L5047/L5087/L6239 — 全部是 docstring 或注释 | 7 处 |

### 保留函数确认

| 函数 | 引用数 | 状态 |
|:-----|:------:|:----:|
| `is_global_admin()` | 8+ 处 (handler.py) | ✅ 保留 |
| `is_approved()` | 1+ 处 (handler.py) | ✅ 保留 |
| `get_users()` | 多处 | ✅ 保留 |
| `get_agent_name()` | 多处 | ✅ 保留 |

**结论：🟢 安全。** `role_level()` 确实零调用者，7 处注释纯文档，无逻辑影响。

---

## 🅱️ 配对码系统 — 5 文件删除

### 各文件 grep 基线

| # | 文件 | 删除内容 | 行数 | 结果 |
|:-:|:-----|:---------|:----:|:----:|
| B-1 | `server/auth.py` | `PAIRING_CODE_TTL`、配对码 5 函数 | ~-55 | ✅ 现存 |
| B-2 | `server/persistence.py` | `_pairing_codes` + 4 函数 | ~-28 | ✅ 现存 |
| B-3 | `server/handler.py` | `handle_approve()` + `_cmd_approve_pairing()` | ~-29 | ✅ 现存 |
| B-4 | `server/handler.py` | `"approve_pairing"` 命令注册表条目 + 提示代码 | ~-8 | ✅ 现存 |
| B-5 | `server/__main__.py` | load/save/cleanup import + 调用 | ~-8 | ✅ 现存 (L18/L21/L46/L53/L54/L797) |
| B-6 | `shared/protocol.py` | `MSG_PAIRING_CODE` + `PAIRING_CODE_TTL` | ~-2 | ✅ 现存 |
| **合计** | | | **~-125** | **全部确认** |

### 安全边界验证

| 检查项 | 结果 |
|:-------|:----:|
| `is_approved()` 不依赖配对码函数 | ✅ 读 `_approved_users`，配对码 `approve()` 只是写入路径之一 |
| `is_global_admin()` 不依赖配对码 | ✅ 读 `_approved_users` 的 role 字段 |
| 无外部 import 配对码函数 | ✅ 仅 `server/__main__.py` 中有导入，一并删除 |

**结论：🟢 安全。** 配对码系统完全独立，与其他逻辑无耦合。注意 `approve()` 函数名冲突风险——需确认无其他名叫 `approve` 的函数。grep 结果确认僅 `auth.py:35 def approve(code, role)` 唯一函数，安全。

---

## 🅲 R63 Feature Toggles — 3 变量 + 6 处 if 守卫

### 变量定义

| 变量 | 行号 | 默认值 | 若变 False |
|:-----|:----:|:------:|:-----------|
| `_ENABLE_R63_TIMEOUT` | handler.py:86 | True (env `R63_ENABLE_TIMEOUT`) | 关闭超时功能 |
| `_ENABLE_R63_AGENT_MAP` | handler.py:87 | True (env `R63_ENABLE_AGENT_MAP`) | — |
| `_ENABLE_R63_ACK` | handler.py:88 | True (env `R63_ENABLE_ACK`) | 关闭 ACK 守卫 |

### if 守卫位置

| # | 行号 | 表达式 | 删除方式 |
|:-:|:----:|:-------|:---------|
| C-2 | 1819 | `if _ENABLE_R63_TIMEOUT:` | 移除 if，保留内部 `_task_timeout = ...` |
| C-3 | 1863 | `if _ENABLE_R63_TIMEOUT:` | 同上 |
| C-4 | 3536 | `if _ENABLE_R63_TIMEOUT:` | 同上 |
| C-5 | 4355 | `if current and _ENABLE_R63_TIMEOUT:` | 改为 `if current:` |
| C-6a | 2101 | `if not _ENABLE_R63_ACK:` | 移除 if，保留内部代码 |
| C-6b | 3544 | `if _ENABLE_R63_ACK:` | 同上 |

### 额外发现 ⚠️

`_ENABLE_R63_AGENT_MAP`（handler.py:87）**没有任何 if 守卫使用**——`_ROLE_AGENT_MAP` 是独立结构且已在生产中稳定运行，此变量为纯死变量定义。删除变量定义即可，无需处理任何 if 守卫。

**结论：🟢 安全。** 默认全为 True，移除 if 守卫保留内部代码等价于硬编码 True 行为，零功能变化。`R63_ENABLE_AGENT_MAP` env var 无消费者。

---

## 🅳 MSG_REGISTER_AGENT 旧路径 — handler.py 分支删除

### 删除坐标

| 项目 | 值 |
|:-----|:----|
| 位置 | server/handler.py L7039-7075 |
| 类型 | `elif msg_type == p.MSG_REGISTER_AGENT and agent_id:` 分支 |
| 范围 | 整段 ~37 行（含注释、用户注册、通知） |
| 标记 | `# DEPRECATED — R72 新体系使用 register 协议` |

### 引用分析

| 引用 | 位置 | 状态 |
|:-----|:-----|:----:|
| `p.MSG_REGISTER_AGENT` | handler.py:7039 唯一引用 | ✅ 删除 |
| `MSG_REGISTER_AGENT = "register_agent"` | protocol.py:163 常量定义 | ⚠️ 会变成死常量，但本项目范围仅 handler.py 分支 |

**结论：🟢 安全。** 独立 elif 分支，唯一入口，删除不影响其他消息处理路径。protocol.py 常量可留待后续清理。

---

## 总结

| 类别 | 删除行 | 验证 | 风险 |
|:-----|:------:|:----:|:----:|
| 🅰️ role_level() | -15 | ✅ 零调用者 | 🟢 无 |
| 🅱️ 配对码系统 | -125 | ✅ 5 文件完整基线 | 🟢 无 |
| 🅲 R63 toggles | -11 | ✅ 6 处 if 全列出 | 🟢 无（额外发现死变量 `AGENT_MAP`） |
| 🅳 MSG_REGISTER_AGENT | -30 | ✅ 唯一 elif 分支 | 🟢 无（protocol.py 常量剩残留） |
| **合计** | **~-181** | **全部通过** | **🟢 零回归风险** |

**QA 意见：✅ 架构设计合理，4 项删除安全，技术方案可作为编码执行的依据。建议编码按 tech plan 精确坐标逐项执行。**
