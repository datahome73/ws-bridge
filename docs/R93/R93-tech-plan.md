---
pipeline:
  name: "R93 做减法 — 清理等级体系/配对码/R63 toggles/旧注册路径 🧹"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R93/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R93/R93-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 技术方案
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
    step2:  { role: architect,    title: 技术方案 }
    step3:  { role: developer,    title: 编码清理 }
    step4:  { role: reviewer,     title: 代码审查 }
    step5:  { role: qa,           title: 测试验证 }
    step6:  { role: operations,   title: 合并部署归档 }
  workspace:
    members:
      architect: { mention_keyword: "architect;架构师" }
      developer: { mention_keyword: "developer;开发" }
      reviewer:  { mention_keyword: "reviewer;审查" }
      qa:        { mention_keyword: "qa;测试" }
      operations: { mention_keyword: "operations;运维" }
---

# R93 技术方案 — 做减法 🧹

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R93/R93-product-requirements.md` v1.0
> **改动文件：** `server/auth.py` · `server/persistence.py` · `server/handler.py` · `server/__main__.py` · `shared/protocol.py` · `server/config.py`
> **净变化：** -181 行，零新增

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ 等级体系 `role_level()` 删除分析](#️-等级体系-role_level-删除分析)
3. [🅱️ 配对码系统删除分析](#️-配对码系统删除分析)
4. [🅲 R63 Feature Toggles 清理分析](#️-r63-feature-toggles-清理分析)
5. [🅳 MSG_REGISTER_AGENT 旧路径删除分析](#️-msg_register_agent-旧路径删除分析)
6. [异常情况与边界分析](#6-异常情况与边界分析)
7. [删除安全矩阵](#7-删除安全矩阵)
8. [开发者指引](#8-开发者指引)
9. [验收清单](#9-验收清单)

---

## 1. 改动总览

### 1.1 四项删除汇总

| # | 类别 | 文件 | 净行数 | 优先级 |
|:-:|:-----|:-----|:------:|:------:|
| 🅰️ | L1-L4 等级体系 | auth.py, handler.py | **-15** | 🔴 零调用者 |
| 🅱️ | 配对码系统 | auth.py, persistence.py, handler.py, __main__.py, protocol.py | **-125** | 🔴 已全替代 |
| 🅲 | R63 toggles | handler.py, config.py | **-11** | 🟡 永远为真 |
| 🅳 | MSG_REGISTER_AGENT | handler.py | **-30** | 🔴 已标 DEPRECATED |
| | **合计** | **6 文件** | **-181** | **纯删除** |

### 1.2 安全前提

每一项删除的共同前提：
1. ✅ `grep -rn` 确认零引用（无 import、无调用、无执行路径）
2. ✅ 已有替代方案（R72 api_key、Agent Cards、register 协议）
3. ✅ 代码自身标注废弃（DEPRECATED 注释、R6/R63 时代标记）

---

## 2. 🅰️ 等级体系 `role_level()` 删除分析

### 2.1 删除对象

| 位置 | 函数/注释 | 删除方式 |
|:-----|:---------|:---------|
| `auth.py:81-105` | `role_level()` 函数 + R6 注释块 | 整块删除 |
| `handler.py:4 处` | `# L2 member` 注释 | 逐行删除 |
| `handler.py:2 处` | `# L4 global admin` 注释 | 逐行删除 |
| `handler.py:1 处` | `# L3` 等残余 | 逐行删除 |

### 2.2 引用追踪

```bash
# 确认零调用
grep -rn 'role_level' server/ --include='*.py'
# 输出应为空
```

### 2.3 B1: 注释删除后代码可读性

删除纯注释行不会影响代码逻辑。但需注意：

```python
# 当前:
# ── R6 check: only L4+ can approve
if not is_global_admin(agent_id):
    return "权限不足"

# 清理后:
if not is_global_admin(agent_id):
    return "权限不足"
```

**结论：** 注释删除 → 代码逻辑完全不受影响 ✅

---

## 3. 🅱️ 配对码系统删除分析

### 3.1 删除范围

| 文件 | 删除内容 | 行数 | 注意 |
|:-----|:---------|:----:|:-----|
| `auth.py` | `PAIRING_CODE_TTL`, `generate_code()`, `create_pairing_code()`, `approve()`, `cleanup_expired_codes()`, `_code_expired()` | -50 | 整块删除，保留 `approved_users` 相关函数 |
| `persistence.py` | `_pairing_codes`, `load_pairing_codes()`, `save_pairing_codes()`, `get_pairing_codes()`, `set_pairing_codes()` | -28 | 确认 `_approved_users` 函数不受影响 |
| `handler.py` | `handle_approve()`, `_cmd_approve_pairing()`, 注册表条目, approve 提示代码 | -34 | 确认无其他路径调用 |
| `__main__.py` | `load_pairing_codes`/`save_pairing_codes` import 和调用 + cleanup loop | -8 | 确认 `load_approved_users`/`save_approved_users` 不受影响 |
| `protocol.py` | `MSG_PAIRING_CODE`, `PAIRING_CODE_TTL` 常量 | -2 | DEPRECATED 标记同删 |

### 3.2 引用追踪

```bash
# 确认无残留引用
grep -rn 'generate_code\|create_pairing_code\|approve(\|cleanup_expired_codes\|pairing_codes\|MSG_PAIRING_CODE' server/ shared/ --include='*.py'
```

### 3.3 B2: approved_users 与 pairing_codes 的分离

**关键确认：** `approved_users` 和 `pairing_codes` 是独立的数据结构和函数，不存在交叉引用。

```python
# persistence.py 中两者完全分离:
_approved_users: dict = {}       # 保留 ✅
_pairing_codes: dict = {}        # 删除 🗑️

def load_approved_users(...)     # 保留 ✅
def save_approved_users(...)     # 保留 ✅
def get_approved_users(...)      # 保留 ✅
def set_approved_users(...)      # 保留 ✅

def load_pairing_codes(...)      # 删除 🗑️
def save_pairing_codes(...)      # 删除 🗑️
def get_pairing_codes(...)       # 删除 🗑️
def set_pairing_codes(...)       # 删除 🗑️
```

### 3.4 B3: `_pairing_codes.json` 文件残留

```python
# 当前:
PAIRING_CODES_FILE = os.path.join(data_dir, "_pairing_codes.json")

# 删除后:
# 文件仍可留在磁盘上，服务不再加载
# 安全地手动删除（Ops 步骤）
```

**风险：** 无。文件存在但不再被读取。

---

## 4. 🅲 R63 Feature Toggles 清理分析

### 4.1 删除范围

| 位置 | 删除内容 | 操作 |
|:-----|:---------|:-----|
| `handler.py:86-88` | `_ENABLE_R63_TIMEOUT`, `_ENABLE_R63_AGENT_MAP`, `_ENABLE_R63_ACK` 定义 | 删除 3 行 |
| `handler.py:1819` | `if _ENABLE_R63_TIMEOUT:` | 移除 if，保留内部代码 |
| `handler.py:1863` | `if _ENABLE_R63_TIMEOUT:` | 移除 if，保留内部代码 |
| `handler.py:3536` | `if _ENABLE_R63_TIMEOUT:` | 移除 if，保留内部代码 |
| `handler.py:4355` | `if current and _ENABLE_R63_TIMEOUT:` → `if current:` | 移除后半 |
| `handler.py:3 处` | `if _ENABLE_R63_ACK:` | 移除 if，保留内部代码 |
| `config.py` | `R63_ENABLE_*` 3 个配置项 | 删除 |

### 4.2 B4: `if _ENABLE_R63_TIMEOUT:` 守卫移除

所有 `if _ENABLE_R63_TIMEOUT:` 守卫的内部代码在 toggle 为 `"1"` 时都会执行。删除 if 后，内部代码变成无条件执行——与当前生产行为一致。

**示例：**

```python
# 当前:
if _ENABLE_R63_TIMEOUT:
    _task_timeout = int(params.get("timeout", 7200))
# else: timeout 为 None → 默认无超时

# 删除后:
_task_timeout = int(params.get("timeout", 7200))
```

### 4.3 B5: `_ENABLE_R63_ACK` 守卫移除

同 B4，删除 `if _ENABLE_R63_ACK:` 后内部代码无条件执行，与当前生产行为一致。

### 4.4 B6: `_ENABLE_R63_AGENT_MAP` 引用确认

```bash
# 预期输出：仅定义行，无使用行
grep -rn 'R63_AGENT_MAP\|ENABLE_AGENT_MAP' server/ shared/ --include='*.py'
```

_Note: 需求文档已确认该变量定义后从未在任何 `if` 判断中使用。_

---

## 5. 🅳 MSG_REGISTER_AGENT 旧路径删除分析

### 5.1 删除范围

| 位置 | 删除内容 | 行数 |
|:-----|:---------|:----:|
| `handler.py:7039-7070` | `elif msg_type == p.MSG_REGISTER_AGENT:` 处理分支（约 30 行含注释） | -30 |

### 5.2 B7: 条件判断链完整性

`MSG_REGISTER_AGENT` 处理分支位于 `if-elif` 链中。删除该分支后，需要确保相邻的 `elif` / `else` 不受影响。

```python
# 当前结构（简化）:
if msg_type == ADMIN_MSG:          # ← 保A留
    ...
elif msg_type == MSG_COMMAND:      # ← 保留
    ...
elif msg_type == MSG_REGISTER_AGENT:  # ← 删除 🗑️
    ...
elif msg_type == MSG_BROADCAST:    # ← 保留
    ...

# 删除后:
if msg_type == ADMIN_MSG:
    ...
elif msg_type == MSG_COMMAND:
    ...
elif msg_type == MSG_BROADCAST:    # ← 自动衔接
    ...
```

**注意：** 删除的是整个 `elif` 块（包括条件、body、注释），不能留下空的 `elif` 或破损的 `if` 链。开发者需要确认修改后的 `if-elif` 语法完整。

### 5.3 B8: protocol.py `MSG_REGISTER_AGENT` 常量

```python
# protocol.py — 是否还需保留该常量？
MSG_REGISTER_AGENT = "register_agent"
```

**分析：** 如果 `handler.py` 是该常量的唯一引用处，则删除 handler.py 引用后，`protocol.py` 中可同时删除。但该常量可能被外部客户端使用（理论上）。**建议只删除 handler.py 中的使用，保留 protocol.py 定义**（如同已标 DEPRECATED 的 `MSG_PAIRING_CODE`，待后续轮单独清理）。

---

## 6. 异常情况与边界分析

### 6.1 风险矩阵

| # | 风险场景 | 等级 | 缓解措施 |
|:-:|:---------|:----:|:---------|
| R1 | `handle_approve()` 被外部队列或定时器引用 | 🟢 | `grep -rn 'handle_approve'` 确认零引用 |
| R2 | `__main__.py` cleanup 循环删除后 asyncio 循环结构变化 | 🟡 | 确认 asyncio 循环中其他 task 不受影响 |
| R3 | 删除 `if _ENABLE_R63_TIMEOUT:` 后缩进错误 | 🟡 | 开发者注意缩进对齐，`ast.parse` 验证 |
| R4 | `_cmd_approve_pairing` 命令注册表删除后 Web 前端报错 | 🟢 | 前端不依赖服务端命令注册表条目 |
| R5 | `is_global_admin()` 间接依赖 `approved_users` 但删除配对码相关代码 | 🟢 | `approved_users` 函数完全保留 |
| R6 | 客户端发送旧的 `MSG_PAIRING_CODE` 或 `MSG_REGISTER_AGENT` | 🟢 | 客户端使用 R72 register，旧消息类型被忽略（switch 默认分支） |

### 6.2 asyncio 循环完整性

`__main__.py` 中有一个 60s 间隔的配对码清理循环：

```python
# 当前:
async def periodic_cleanup():
    while True:
        await asyncio.sleep(60)
        cleanup_expired_codes()

# 或是在 main() 中作为 asyncio.create_task 启动
```

**删除方案：** 直接删除整个 `periodic_cleanup()` 函数（如存在）+ 其启动调用。不影响其他 `asyncio.create_task`（如 ping 保活、消息处理循环）。

### 6.3 文件残留

删除代码后以下文件不再被访问：

| 文件 | 状态 | 操作 |
|:-----|:-----|:-----|
| `_pairing_codes.json` | 不再加载/写入 | 可安全删除（Ops 步骤） |
| `_approved_users.json` | 继续使用 | **保留不动** ✅ |

---

## 7. 删除安全矩阵

| 删除项 | 零调用确认 | 替代方案 | 标注废弃 | 回归风险 |
|:-------|:----------:|:--------:|:--------:|:--------:|
| 🅰️ `role_level()` | ✅ grep=0 | L2/L4 区分已不用 | ✅ R6 时代 | 🟢 零 |
| 🅱️ 配对码系统 | ✅ grep=0 | R72 api_key | ✅ DEPRECATED | 🟢 零 |
| 🅲 R63 toggles | ✅ grep=0（AGENT_MAP）+ 永远为真 | 无需 toggle | ✅ R63 时代 | 🟢 零 |
| 🅳 MSG_REGISTER_AGENT | ✅ 仅 DEPRECATED 标 | R72 register | ✅ 注释说明 | 🟢 零 |

---

## 8. 开发者指引

### 8.1 操作顺序（建议）

```
1. 先清理 🅲 (R63 toggles) — 改动最小，最安全
2. 再清理 🅳 (MSG_REGISTER_AGENT) — 单文件单分支
3. 再清理 🅰️ (role_level) — 跨文件但改动浅
4. 最后清理 🅱️ (pairing codes) — 最复杂，跨 5 文件
```

### 8.2 每一步后执行

```bash
# 语法检查
python3 -c "import ast; ast.parse(open('server/handler.py').read()); print('OK')"
for f in server/auth.py server/persistence.py server/__main__.py shared/protocol.py server/config.py; do
    python3 -c "import ast; ast.parse(open('$f').read()); print('$f: OK')" || echo "$f: FAIL"
done

# 残留检查
grep -rn 'role_level\|generate_code\|pairing_code\|R63_ENABLE\|MSG_REGISTER_AGENT' server/ shared/ --include='*.py' | grep -v 'R93:'
```

### 8.3 提交格式

```
feat(R93): 🧹 做减法 — delete role_level/pairing_codes/R63_toggles/MSG_REGISTER_AGENT
```

或分 4 个子提交（需确认 pipeline 是否接受多 commit）：

```
feat(R93-A): delete role_level() + L2/L4 comments
feat(R93-B): delete pairing code system (5 files)
feat(R93-C): delete R63_ENABLE_* feature toggles
feat(R93-D): delete MSG_REGISTER_AGENT handling path
```

---

## 9. 验收清单

| # | 验收项 | 验证方式 | 期望 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | `role_level()` 从 auth.py 删除 | `grep -rn 'role_level'` | 空 |
| 🅰️-2 | handler.py L2/L4 注释清理 | `grep 'L[0-9] member\|L[0-9] global\|L[0-9] observer'` | 空 |
| 🅱️-1 | auth.py 配对码函数删除 | `grep 'generate_code\|create_pairing_code\|approve('` | 空 |
| 🅱️-2 | persistence.py 配对码函数删除 | `grep 'pairing_codes'` | 空 |
| 🅱️-3 | handler.py handle_approve/approve_pairing 删除 | `grep 'handle_approve\|approve_pairing'` | 空 |
| 🅱️-4 | __main__.py 配对码加载/清理删除 | `grep 'pairing_codes\|cleanup_expired'` | 空 |
| 🅱️-5 | protocol.py MSG_PAIRING_CODE/PAIRING_CODE_TTL 删除 | `grep 'MSG_PAIRING_CODE\|PAIRING_CODE_TTL'` | 空 |
| 🅲-1 | handler.py `_ENABLE_R63_*` 定义删除 | `grep 'ENABLE_R63'` | 空 |
| 🅲-2 | config.py R63_ENABLE 配置项删除 | `grep 'R63_ENABLE'` | 空 |
| 🅲-3 | 4 处 `if _ENABLE_R63_TIMEOUT:` 守卫移除 | 代码审查 | 内部代码无条件 |
| 🅲-4 | 2 处 `if _ENABLE_R63_ACK:` 守卫移除 | 代码审查 | 内部代码无条件 |
| 🅳-1 | handler.py `MSG_REGISTER_AGENT` 分支删除 | `grep 'MSG_REGISTER_AGENT'` | 仅 protocol.py |
| ✅-1 | 总删除 ≥ 180 行 | `git diff --stat` | ≥ -180 |
| ✅-2 | 零新增行 | `git diff --stat` | 0 新增 |
| ✅-3 | 全部文件 ast.parse 通过 | `python3 -c "import ast; ast.parse(...)"` | 均 OK |
