# R131 Step 4 — 代码审查报告 🔍

> **轮次：** R131  
> **审查人：** 小周  
> **Commit：** `0fbe8560` (feat(R131): Step 3 — ##query规则族（rule 25）+ 5查询子命令)  
> **涉及文件：** `scenario_matcher.py` (+184行) / `main.py` (+13行)  
> **依据：** R131 需求文档 v1.1

---

## 1️⃣ 编译验证 ✅

| 文件 | 原行数 | 变更 | 编译结果 |
|:-----|:------:|:----:|:--------:|
| `scenario_matcher.py` | 258 | +184 | ✅ 零错误 |
| `main.py` | 4926 | +13 | ✅ 零错误 |

---

## 2️⃣ 正向验证 — 架构完整性

| 验收项 | 结果 | 说明 |
|:-------|:----:|:------|
| Rule 25 注册于 priority=25 | ✅ | 介于 to_agent(20) 和 ##(30) 之间，正确 |
| `match_query` 匹配函数 | ✅ | `content.startswith("##query")`，返回 content 传给 handle |
| `handle_query` 处理函数 | ✅ | 解析 `##query##<sub_cmd>[##<params>]` 格式 |
| 6 个子命令路由 | ✅ | whoami / status / agents / agent_info / audit / help |
| 权限模型 | ✅ | L1→whoami/help; L3→查询类; L4→全部(含audit) |
| main.py 桥接 `_sm_handle_query` | ✅ | 注册规则回调，遵循已有模式 |
| `_send_reply` 复用 | ✅ | 回复仅发到发送者 inbox，不广播 |

### 2.1 权限检查完整性

```
handle_query 入口
  ├── _get_agent_level(agent_id) → level
  ├── level < 1 → ❌ 未注册 bot
  ├── level == 1 && sub_cmd ∉ {whoami, help} → ❌ L1 限制
  ├── level < 4 && sub_cmd == "audit" → ❌ L4 要求
  └── 通过 → 路由
```

权限三元组覆盖正确，符合 PRD §2.3。

### 2.2 规则覆盖

```
"##query##whoami"        → Rule 25 → handle_query → whoami ✅
"##query##status"        → Rule 25 → handle_query → status ✅
"##query##agents"        → Rule 25 → handle_query → agents ✅
"##query##agent_info"    → Rule 25 → handle_query → agent_info ✅
"##query##audit"         → Rule 25 → handle_query → audit ✅
"##query##help"          → Rule 25 → handle_query → help ✅
"##start##R130"          → Rule 30 → hash_cmd ✅
"##status##R130"         → Rule 30 → hash_cmd ✅
```

---

## 3️⃣ 🔴 严重问题 #1 — 快捷命令不工作

**文件：** `scenario_matcher.py` — `match_query()` (L226-232)  
**风险等级：** 🔴 **CRITICAL**

### 现象

PRD §2.6 明确列出 `##whoami`、`##agents`、`##agent_info`、`##audit` 为可用命令格式。但当前 `match_query` 仅匹配 `##query` 前缀：

```python
def match_query(content, msg, agent_id):
    if content.startswith("##query"):
        return content
    return False
```

用户发送 `##whoami` 不会命中 Rule 25，而是落入 Rule 30 (`match_hash_cmd`)，被 `handle_hash_cmd` 解析失败后**显示不相关的通用 `##` 帮助信息**。

### 测试验证

| 输入 | 命中规则 | 实际行为 |
|:-----|:--------:|:---------|
| `##query##whoami` | Rule 25 ✅ | 正常回复 whoami |
| `##whoami` | Rule 30 ❌ | 显示通用 ## 帮助 |
| `##agents` | Rule 30 ❌ | 显示通用 ## 帮助 |
| `##agent_info ws_xxx` | Rule 30 ❌ | 显示通用 ## 帮助 |
| `##audit` | Rule 30 ❌ | 显示通用 ## 帮助 |

### 修复建议

```python
_QUERY_SHORTCUTS = ("##whoami", "##agents", "##status", "##agent_info", "##audit", "##help")

def match_query(content, msg, agent_id):
    if content.startswith("##query"):
        return content
    for prefix in _QUERY_SHORTCUTS:
        if content.startswith(prefix):
            return content.replace("##", "##query##", 1)
    return False
```

---

## 4️⃣ 🔴 严重问题 #2 — 转义序列错误（`\\\\n` → 应改为 `\\n`）

**文件：** `scenario_matcher.py`（约 15 处）  
**风险等级：** 🔴 **CRITICAL**

### 现象

所有新增字符串使用了 `\\\\n`（Python 源码中 4 反斜杠），运行时产出**文字 `\n`**而非实际换行。客户端将看到 `\n` 字样。

### 根因分析

| 代码 | 文件内容 | Python 字符串 | 实际值 |
|:-----|:---------|:-------------|:-------|
| **旧代码** (L173) | `\\n` ✅ | `\n` ✅ | 换行 ✅ |
| **新代码** (L245) | `\\\\n` ❌ | `\\n` ❌ | 文字 `\n` ❌ |
| **新代码** f-strings (L279) | `\\\\n` ❌ | `\\n` ❌ | 文字 `\n` ❌ |
| **新代码** join 分隔 (L337) | `"\\\\n"` ❌ | `"\\n"` ❌ | 文字 `\n` ❌ |

### 波及范围（需修复 `\\\\n` → `\\n`）

| 行号 | 内容 |
|:----:|:-----|
| 245 | `"📋 **##query 命令**\\\\n\\\\n"` |
| 246-250 | `"##whoami ...\\\\n"` |
| 279-280 | `f"🆔...\\\\n"` (whoami 输出) |
| 296-301 | `"📋 **##query 命令**\\\\n\\\\n"` (help 文本) |
| 337 | `return "\\\\n".join(lines)` |
| 359 | `return "\\\\n".join(lines)` |
| 379-385 | `f"\\\\n  📇 ..."` (agent_info f-strings) |
| 402 | `"📋 最近审计日志:\\\\n"` |

---

## 5️⃣ 🟡 警告 — 可选优化

### 5.1 if/elif 路由建议用 dict 映射

6 路子命令的 if/elif 链可改为 dict 映射，当前无功能问题。

### 5.2 `_get_agent_level` 可考虑共享

如需跨模块复用，可提到共享模块。本轮不受影响。

---

## 6️⃣ 🟢 已通过项汇总

| # | 验收项 | 状态 |
|:-:|:-------|:----:|
| F1 | `##query##whoami` 回复 agent_id + 级别 | ✅ |
| F2 | `##query##agents` 列出所有 bot | ✅ |
| F3 | `##query##status` 回复活跃管线 | ✅ |
| F4 | `##query##status##R130` 指定管线详情 | ✅ |
| F5 | `##query##agent_info ws_xxx` bot 详情 | ✅ |
| F6 | `##query##audit` L4 有权限 / L3 拒绝 | ✅ |
| R1 | `##start`/`##stop`/`##status` 等不受影响 | ✅ |
| R2 | `!` 命令仍可用 | ✅ |
| R3 | `_handle_server_query` 仍可用 | ✅ |
| R4 | to_agent 派活不受影响 | ✅ |
| R5 | 回复仅发到发送者 inbox | ✅ |

---

## 7️⃣ 审查裁决

| 维度 | 结论 |
|:-----|:------|
| 编译 | ✅ PASS |
| 架构设计 | ✅ Rule 25 注册正确，权限模型完整，6 子命令齐全 |
| 功能完整性 | ❌ **2 个 Critical 缺陷**（快捷命令 + 转义序列） |

### 裁决：⏸ **暂缓合入** — 需修复 2 个 Critical 后重审

**修复清单：**
1. `match_query` 增加快捷命令匹配（~5 行）
2. `scenario_matcher.py` 全部 `\\\\n` → `\\n`（约 15 处，~20 字符修正）

修复量：~20 行，无业务逻辑变更。
