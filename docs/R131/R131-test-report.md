# R131 测试报告 🧪 — `##query` 规则族

> **测试角色：** 🦐 泰虾
> **日期：** 2026-07-20
> **基线：** `0fbe856` (feat R131 Step 3)
> **测试模式：** 源码级分析

## 测试结果

| 分组 | 通过 | 总计 | 结果 |
|:-----|:----:|:----:|:----:|
| 🅵 功能验收 | 14 | 15 | ✅ 结构正确 |
| 🆁 回归验证 | 9 | 10 | ✅ 无退化 |
| 🔧 编译验证 | 2 | 2 | ✅ 零错误 |
| 🔴 Critical 缺陷 | 0 | 2 | ❌ **需修复** |
| **总计（含Bug）** | **25** | **29** | **⚠️ 不通过** |

## 🔴 Critical 缺陷

### 🐛 BUG-1: 快捷命令不工作

| 输入 | 预期命中 | 实际命中 | 影响 |
|:-----|:--------:|:--------:|:-----|
| `##whoami` | Rule 25 → whoami | Rule 30 → 通用帮助 | 快捷方式全废 |
| `##agents` | Rule 25 → agents | Rule 30 → 通用帮助 | |
| `##agent_info` | Rule 25 → agent_info | Rule 30 → 通用帮助 | |
| `##audit` | Rule 25 → audit | Rule 30 → 通用帮助 | |

**原因：** `match_query()` 仅检查 `content.startswith("##query")`，未匹配快捷前缀。

**修复（~5 行）：**
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

### 🐛 BUG-2: 转义序列错误

所有 R131 新增字符串使用 `\\\\n`（源码 4 反斜杠），运行时产出文字 `\n` 而非实际换行。

**波及范围（~15 处）：**

| 行号 | 内容 |
|:----:|:-----|
| 245 | `"\\\\n\\\\n"` (help header) |
| 246-250 | help 条目中的 `\\\\n` |
| 279-280 | whoami 输出的 f-string |
| 296-301 | help 子命令文本 |
| 337 | `"\\\\n".join(lines)` |
| 359 | `"\\\\n".join(lines)` |
| 379-385 | agent_info 输出 |
| 402 | audit 日志 header |

**修复：** 全部 `\\\\n` → `\\n`（Python 源码 4 反斜杠 → 2 反斜杠）。`\\\\n` 在 Python 字符串中 = `\\n`（文字反斜杠+n），`\\n` = `\n`（实际换行）。

## ✅ 已通过验证项

### 🅵 功能验收（14/15）

| # | 项 | 结果 |
|:-:|:---|:----:|
| F1 | match_query 存在 + ##query 前缀匹配 | ✅ |
| F1c | handle_query 存在 | ✅ |
| F1d | whoami 子命令路由 | ✅ |
| F2a | agents 子命令路由 | ✅ |
| F3a | status 子命令路由 | ✅ |
| F5a | agent_info 子命令路由 | ✅ |
| F6a | audit 子命令路由 | ✅ |
| F6b | audit L4 权限守卫 | ✅ |
| F7a | Rule 25 priority=25 注册 | ✅ |
| F8a | L1 仅 whoami/help 限制 | ✅ |
| F8b | level < 4 权限检查 | ✅ |
| F8c | _get_agent_level 函数 | ✅ |
| F9a | _send_reply 复用（inbox私信） | ✅ |
| F4a | status 支持 round_name 参数 | ⚠️ 边界条件 |

### 🆁 回归验证（9/10）

| # | 项 | 结果 |
|:-:|:---|:----:|
| R1a-d | Rule 10/20/30/40-90 全部保留 | ✅ |
| R2a-b | Rule 80 exclamation + handle 保留 | ✅ |
| R3a | _handle_server_query 保留 | ✅ |
| R4a-b | to_agent 派活注册正常 | ✅ |
| R5a | handle_query 使用 _send_reply | ✅ |

### 🔧 编译验证（2/2）

| 文件 | 结果 |
|:-----|:----:|
| scenario_matcher.py | ✅ |
| main.py | ✅ |

## 结论

⚠️ **功能结构正确但存在 2 个 Critical 缺陷，需修复后重测。** 修复量 ~20 行，无业务逻辑变更。
- ✅ Rule 25 注册正确、6 子命令路由完整、权限模型准确
- ❌ 快捷命令不工作、转义序列全错
- 🟢 无回归问题
