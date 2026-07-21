# R139 产品需求 — main.py 规则回调+注册提取轮

> **起草人：** 🧐 PM
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据文档：** `server/ws_server/README.md` §9 重构清单

---

## 1. 背景与目标

### 1.1 现状

R137（引擎分拆）+ R138（引擎合并）后，`main.py` 已从峰值 ~6,400 行精简到 **736 行**，但最后还有两坨代码留在 main.py 中：

| 段落 | 行号 | 行数 | 内容 |
|:----|:----:|:----:|:------|
| `_sm_handle_*()` 规则回调 | L469-L657 | ~190 行 | 8 个 scenario_matcher 规则处理函数 |
| 规则注册代码 | L660-L735 | ~76 行 | 注册全部 HandlerRule 实例 |
| **合计** | **L469-L735** | **~266 行** | **可提取的残留代码** |

这 266 行是 **main.py 与 scenario_matcher 的桥接代码**——核心消息路由逻辑不在这，管线推进逻辑也不在这（已迁入 pipeline_engine）。它们是规则匹配后的"动作响应"，本质上是 scenario_matcher 规则系统的一部分。

### 1.2 现存问题

| # | 问题 | 当前代码 |
|:-:|:-----|:---------|
| 1 | main.py 职责不纯 — 包含规则回调+注册 | 736 行中有 266 行是规则系统的"胶水代码" |
| 2 | 规则注册在 module level 执行，import main.py 就会触发 | 导致 scenario_matcher.py 无法在顶部 import main.py（需用函数体内 lazy import） |
| 3 | 新规则添加要改两个文件（scenario_matcher 加匹配函数 + main.py 加回调+注册） | 不直观，易遗漏 |
| 4 | **潜在 bug：** scenario_matcher.py L515 引用 `_main` 变量但从未定义 | 触发 `##status` 时未定义变量报错 |

### 1.3 目标

**将 main.py 的规则回调 + 注册代码提取为独立模块，main.py 只保留 WS 路由核心逻辑（~470 行）。**

```
提取前:                          提取后:
main.py (736 行)                main.py (~470 行)
├── imports/state (69 行)       ├── imports/state (69 行)
├── 辅助函数 (135 行)            ├── 辅助函数 (135 行)
├── re-export 模块 (52 行)       ├── re-export 模块 (52 行)
├── handle_broadcast (78 行)    ├── handle_broadcast (78 行)
├── handler() (76 行)           ├── handler() (76 行)
├── _sm_handle_*() 回调 (190行)  ├── import scene_rules
└── 规则注册 (76 行)             └── 调用 register_rules()

                                scenario_rules.py (~270 行)【新增】
                                ├── 所有 _sm_handle_*() 回调
                                └── register_all_rules() 函数
```

---

## 2. 核心设计与改动范围

### 2.1 方案：创建 `scenario_rules.py`

创建新文件 `server/ws_server/scenario_rules.py`，包含：

**① 全部 8 个规则回调函数（逐字迁移）：**

| 函数 | 规则 | 优先级 | 行号来源 (main.py) |
|:-----|:-----|:------:|:------------------|
| `_sm_handle_loopback` | 回路测试 | 10 | L469-L484 |
| `_sm_handle_to_agent` | to_agent 派活路由 | 20 | L487-L520 |
| `_sm_handle_hash` | `##` 命令路由 | 30 | L523-L525 |
| `_sm_handle_query` | `##query` 命令 | 25 | L528-L530 |
| `_sm_handle_step` | `##step` 命令 | 28 | L533-L535 |
| `_sm_handle_ack` | ACK 转发 | 40 | L538-L553 |
| `_sm_handle_complete` | 完成确认 | 50 | L556-L582 |
| `_sm_handle_reject` | 退回回退 | 60 | L585-L609 |
| `_sm_handle_fail` | 失败告警 | 70 | L612-L635 |
| `_sm_handle_catchall` | 入库留痕 | 90 | L638-L657 |

**② 全部 10 条规则注册 → 封装为 `register_all_rules()` 函数：**

| 规则 | 匹配函数 | 处理函数 | 优先级 |
|:-----|:---------|:---------|:------:|
| loopback | `match_loopback` | `_sm_handle_loopback` | 10 |
| to_agent | `match_to_agent` | `_sm_handle_to_agent` | 20 |
| query | `match_query` | `_sm_handle_query` | 25 |
| step | `match_step` | `_sm_handle_step` | 28 |
| hash_cmd | `match_hash_cmd` | `_sm_handle_hash` | 30 |
| ack | `match_ack` | `_sm_handle_ack` | 40 |
| complete | `match_complete` | `_sm_handle_complete` | 50 |
| reject | `match_reject` | `_sm_handle_reject` | 60 |
| fail | `match_fail` | `_sm_handle_fail` | 70 |
| catchall | `match_catchall` | `_sm_handle_catchall` | 90 |

### 2.2 依赖关系

回调函数使用的依赖项及引入方式：

| 依赖 | 来源 | 引入方式 |
|:-----|:-----|:---------|
| `_send()` | `connection_manager` | 顶部 import |
| `_send_to_agent()` | `connection_manager` | 顶部 import |
| `_is_valid_agent_id()` | `connection_manager` | 顶部 import |
| `ms.save_message()` | `message_store` | `from . import message_store as ms` |
| `state._r72_users` | `state` | `from . import state` |
| `state.SYSTEM_AGENT_ID` | `state` | 同上 |
| `config.DISPATCH_SENDER_ID` | `server.common.config` | 顶部 import |
| `config.PIPELINE_PM_AGENT_ID` | `server.common.config` | 同上 |
| `_ensure_engine()` | `main` | 函数体内 `from .main import _ensure_engine`（防循环依赖） |
| `_sm.match_*` | `scenario_matcher` | 函数体内 import（注册用） |
| `_sm.register_rule()` | `scenario_matcher` | 函数体内 import |
| `_sm.HandlerRule` | `scenario_matcher` | 函数体内 import |

**使用函数体内 lazy import（`from .main import _ensure_engine`）** — 这是 scenario_matcher.py 已建立的模式（L297 `from .main import _connections`），不会引入循环依赖，因为 `register_all_rules()` 在 main.py 的 module level 被调用时才执行注册。

### 2.3 main.py 的变化

```python
# 删除 L469-L735（全部 _sm_handle_* + 规则注册）
# 在文件底部替换为：
from .scenario_rules import register_all_rules
register_all_rules()
```

### 2.4 附带的 bug 修复

scenario_matcher.py L515 引用了未定义的 `_main` 变量：

```python
# 当前（bug ❌）：
reply = await _format_pipeline_status(params, _main)

# 修复后（✅）：
from . import main as _main_lazy
reply = await _format_pipeline_status(params, _main_lazy)
```

这个 bug 在 `##query##status` 路径中触发，会导致 NameError。

---

## 3. 改动范围

| 文件 | 当前行数 | 变更类型 | 变更后行数 |
|:-----|:--------:|:---------|:----------:|
| `server/ws_server/main.py` | 736 | 删除 L469-L735（~266 行），追加 2 行 import | **~472** |
| `server/ws_server/scenario_rules.py` | — | **新增** — 回调+注册全部代码 | **~270** |
| `server/ws_server/scenario_matcher.py` | 761 | 修复 L515 `_main` bug | 762（+1 行 import）|
| `server/ws_server/README.md` | 352 | 更新 §1 模块清单 + §9 main.py 重构进度 | ~354 |

**净减少：** -266 + 270 + 1 ≈ **+5 行**（纯提取，行为零变更）

---

## 4. 验收标准

### 4.1 编译验证

| # | 验收项 | 验证方法 | 类型 |
|:-:|:-------|:---------|:----:|
| C1 | `from server.ws_server import main` 无 ImportError | `python3 -c "from server.ws_server import main"` | P0 |
| C2 | `from server.ws_server import scenario_rules` 无 ImportError | `python3 -c "from server.ws_server import scenario_rules"` | P0 |
| C3 | `from server.ws_server import scenario_matcher` 无 ImportError | `python3 -c "from server.ws_server import scenario_matcher"` | P0 |
| C4 | `from server.ws_server import *` 全部模块无错误 | `python3 -c "from server.ws_server import main, scenario_matcher, scenario_rules, pipeline_engine, connection_manager, ack_machine, watchdog, pipeline_timeout, git_sync_scheduler, state, message_store, task_store, audit, agent_card, workspace, timeout_tracker, pipeline_context, pipeline_sync"` | P0 |

### 4.2 功能回归

| # | 验收项 | 验证方法 | 类型 |
|:-:|:-------|:---------|:----:|
| T1 | `test ✅` 回路测试正常 | 发 test ✅ → 收到回路回复 | P0 |
| T2 | `to_agent` 派活路由正常 | 发派活指令 → 目标 bot 收到 | P0 |
| T3 | `##query##whoami` 正常 | `##whoami` → 显示身份 | P0 |
| T4 | `##query##status` 不再报 NameError | `##status##R{N}` → 正常显示 | P0 |
| T5 | `##step##complete` 正常 | 步骤完成 | P0 |
| T6 | `##start##R{N}` 正常启动 | 创建管线 + 派活 Step 1 | P0 |
| T7 | `##stop##R{N}` 正常停止 | 管线停止 | P0 |
| T8 | `收到 ✅` / `ACK ✅` 转发正常 | ACK → PM 收到通知 | P0 |
| T9 | `已完成 ✅` 自动推进正常 | 完成 → 推进到下一步 | P0 |
| T10 | `退回 🔄` 驳回回退正常 | 退回 → rollback | P0 |
| T11 | `失败 ❌` 告警正常 | 失败 → PM 收到告警 | P1 |
| T12 | 兜底入库（规则 90）正常 | 无匹配消息 → 静默入库 | P1 |
| T13 | inbox 单播正常 | `_inbox:{bot_id}` 发消息 → 目标收到 | P0 |

### 4.3 代码审查

| # | 验收项 | 类型 |
|:-:|:-------|:----:|
| R1 | scenario_rules.py 的回调函数与 main.py 原版逐字一致（无行为改动） | P0 |
| R2 | main.py 顶部 import 无循环依赖 | P0 |
| R3 | 规则注册顺序与原来完全一致（10→20→25→28→30→40→50→60→70→90） | P0 |

---

## 5. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| 重命名 `_sm_handle_*()` 函数 | 保持接口不变，零行为变更 |
| 修改 match 函数签名 | 不影响匹配逻辑 |
| 统一/优化回调函数逻辑（如 ACK/完成/退回的 PM 通知有重复代码） | 纯提取轮，不重构不优化 |
| 修改 scenario_matcher 的 dispatch 逻辑 | 规则表路由不变 |
| 修改 handle_broadcast 路由逻辑 | 不变 |

---

## 6. 验收检查表总览

| 分组 | 检查项数 | P0 | P1 |
|:----|:--------:|:--:|:--:|
| 编译验证 C1-C4 | 4 | 4 | — |
| 功能回归 T1-T13 | 13 | 12 | 1 |
| 代码审查 R1-R3 | 3 | 3 | — |
| **合计** | **20** | **19** | **1** |

---

> **审核记录：**
> - v1.0 提交审核
> - 结论：⬜ 待审核
