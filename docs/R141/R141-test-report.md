# R141 测试报告 — 代码清理轮

> **测试人：** 泰虾 (QA)
> **轮次：** R141
> **日期：** 2026-07-21
> **基线：** `b443c49` (R137-R140 重构后)
> **编码：** `2ef071e` (Step 3 A+B 类清理) + `b47f949` (Rule 35 修复)
> **审查：** `f3107ec` (Step 4 ✅ 通过)

---

## 第一部分：源码级清理验证

### A-1. main.py 未使用导入（4处）

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `import os` | 🟢 | 已移除，grep 确认 `os.` 不再出现 |
| `import re` | 🟢 | 已移除，`re.` 不再出现 |
| `from . import task_store as ts` | 🟢 | 已移除，`ts.` 不再出现 |
| `from . import timeout_tracker` | 🟢 | 已移除，`timeout_tracker.` 不再出现 |

### A-2. `__main__.py` 未使用导入（2处）

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `save_approved_users` | 🟢 | 已移除 |
| `save_web_sessions` | 🟢 | 已移除 |

### A-3. `scenario_matcher.py` 未使用导入（1处）

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `import uuid` | 🟢 | 已移除，`uuid.` 不再出现 |

### A-4. `message_store.py` 死函数

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `clear_messages_by_channel()` | 🟢 | 函数已移除，全仓库 0 引用 |

### A-5. main.py 精简 nits

| 修改内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `__import__("time").time()` → `time.time()` | 🟢 | 已替换 |
| `__import__('logging').getLogger` → `logging.getLogger` | 🟢 | 已替换 |
| `register_all_rules` import 移到顶部 | 🟢 | `from .scenario_rules import register_all_rules` 在 L25 |

### B-1. workspace 关闭/归档死代码

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| `_broadcast_workspace_closing()` (~44 行) | 🟢 | 函数已移除，全仓库 0 引用 |
| `_broadcast_workspace_archived()` (~26 行) | 🟢 | 函数已移除，全仓库 0 引用 |
| `from . import workspace as ws_mod` | 🟢 | 已移除（该导入仅被上述两函数使用）|

### B-2. state.py 重复定义

| 删除内容 | 状态 | 证据 |
|:---------|:----:|:------|
| L13 重复 `_PIPELINE_CONFIG: dict[str, dict] = {}` | 🟢 | 已移除，仅保留 L30 版本 |

---

## 第二部分：编译验证

| 测试项 | 结果 |
|:-------|:----:|
| `from server.ws_server import main` | 🟢 |
| `from server.ws_server import scenario_matcher` | 🟢 |
| `from server.ws_server import message_store` | 🟢 |
| `from server.ws_server import state` | 🟢 |
| `from server.ws_server import scenario_rules` | 🟢 |
| `from server.ws_server import __main__` | 🟢 |
| `from server.ws_server import *` | 🟢 |

全部 7 模块导入无断裂。

---

## 第三部分：Rule 35 Bugfix 验证

### 问题复述

`match_pm_guard`（R139 regression `c8af582`）检查 `channel == '_inbox:server'` 时未验证发送者身份，导致**所有 bot 的完成消息被拦截**，无法到达 Rule 50 `match_complete`，管线自动推进静默失效。

### 修复验证

| 检查项 | 结果 | 代码证据 |
|:-------|:----:|:---------|
| 仅 PM 被拦截 | 🟢 | `if pm_id and agent_id == pm_id:` — 身份匹配后才拦截 |
| PM agent_id 正确获取 | 🟢 | `_cfg.DISPATCH_SENDER_ID or _cfg.PIPELINE_PM_AGENT_ID` |
| 非 PM bot 放行 | 🟢 | PM 检查不匹配时 `return False` |
| try/except 保护 | 🟢 | `try: from server.common import config` 防止 import 异常 |

### 协议级验证说明

生产服务端（`wss://wsim.datahome73.cloud/ws`）当前运行的是 **旧 dev 代码**（`dev-legacy`），尚未部署 R141 的 Rule 35 修复。新 dev 以 `main` 为基准重建后尚未上线。因此：

- ✅ **源码级：** `match_pm_guard` 修复逻辑完整正确
- ⏳ **协议级：** 待部署后全链路验证

---

## 第四部分：总结

| 清理类别 | 项数 | 通过 | 失败 |
|:---------|:----:|:----:|:----:|
| A-1: main.py 移除未用导入 | 4 | 4 | 0 |
| A-2: __main__.py 移除未用导入 | 2 | 2 | 0 |
| A-3: scenario_matcher.py 移除 uuid | 1 | 1 | 0 |
| A-4: message_store.py 移除死函数 | 1 | 1 | 0 |
| A-5: main.py 精简 nits | 3 | 3 | 0 |
| B-1: workspace 死代码移除 | 3 | 3 | 0 |
| B-2: state.py 重复定义移除 | 1 | 1 | 0 |
| Rule 35 修复 | 1 | 1 | 0 |
| **合计** | **16** | **16** | **0** |

**🟢 全部通过 — 无回归，无断裂。** 变动行数 +4 / -104 与需求一致。

### 建议

部署后补跑协议全链路测试（重点：`已完成 ✅` 自动推进可被非 PM bot 正常使用）。
