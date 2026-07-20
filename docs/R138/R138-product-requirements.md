# R138 产品需求 — 引擎合并轮：engine2.py 吞并 pipeline_engine.py

> **起草人：** 🧐 PM
> **状态：** ⬜ 待审核
> **版本：** v1.0
> **日期：** 2026-07-20
> **依据文档：** `server/ws_server/README.md` §9 重构清单

---

## 0. R138 定位

```
R135（已上线）— 死代码清理：handle_broadcast + 频道体系精简 (-600行)
R136（已上线）— 纯提取轮：连接管理/看门狗/ACK状态机/Git调度/超时扫描 独立成模块
R137（已上线）— 引擎分拆轮：main.py 管线逻辑迁入 engine2.py，两套引擎并行
R138（本轮）  — 引擎合并轮：engine2.py 吞并 pipeline_engine.py，统一为一套
```

R138 是**已验证代码吸收轮**——以 engine2.py 的生产验证代码为主，吸收旧 pipeline_engine.py 的优点，合二为一。

---

## 1. 背景与目标

### 1.1 现状

R137 后出现三个文件：

| 文件 | 行数 | 角色 | 代码状态 |
|:-----|:----:|:-----|:---------|
| `main.py` | 736 | WS 通信协议 | ✅ 纯协议 |
| `engine2.py` | 1,544 | 管线模块级函数 | ✅ 生产已验证 |
| `pipeline_engine.py` | 1,319 | PipelineEngine class | ❌ 有 B-5 PM fallback bug |

**两套引擎并行，但路由分裂：**

```
##start##R{N}
  └→ scenario_matcher → engine2._handle_hash_start → engine2._auto_dispatch ✅

已完成 ✅ R{N} Step {N}
  └→ scenario_matcher → main._sm_handle_complete → engine.try_advance
     → pipeline_engine.auto_dispatch ❌（PM fallback bug, B-5）
```

### 1.2 路由分裂的根因

两套引擎的分叉历史：

```
R127（过去）： 从 main.py 提取 → pipeline_engine.py（精简版 class，含 bug）
R137（本轮）： 从 main.py 再次提取 → engine2.py     （成熟版 module function）
```

由于 `已完成 ✅` 路径走 `_ensure_engine().try_advance()` → `PipelineEngine.auto_dispatch()`，而 PipelineEngine 来自旧版 `pipeline_engine.py`，所以 B-5 bug 仍在。

### 1.3 目标

**合并为一套，删掉 engine2.py。**

```
合并前：
  engine2.py（已验证）   pipeline_engine.py（有 bug）
       │                        │
       └──────── 合并 ──────────┘
                    ↓
        pipeline_engine.py（统一版）
                  ✅
            删除 engine2.py
```

| 文件 | 行数 | 变化 |
|:-----|:----:|:-----|
| `pipeline_engine.py` | 1,544 | 替换为 engine2 的已验证代码 + 吸收旧版有用功能 |
| `engine2.py` | — | 🗑️ 删除（临时名已完成使命） |
| `main.py` | 736 | 更新 import（engine2 → pipeline_engine） |
| `scenario_matcher.py` | 761 | 更新 import（engine2 → pipeline_engine） |
| `__main__.py` | — | 更新 import（engine2 → pipeline_engine） |

### 1.4 范围界定

| 范围 | 包含 | 不包含 |
|:-----|:-----|:-------|
| 合并 | engine2 代码 → pipeline_engine.py | 非管线逻辑（WS 协议/初始化） |
| 删除 | engine2.py 文件 | 其他文件的删除 |
| import 更新 | main.py / scenario_matcher / __main__.py | pipeline_engine 内部重命名 |
| B-5 修复 | 自动修复（用 engine2 的 auto_dispatch 替换旧版） | 额外的逻辑优化 |

---

## 2. 功能需求

### MERGE-A：替换 pipeline_engine.py 内容

以 engine2.py（已验证代码，模块级函数）为主体，替换 pipeline_engine.py 的全部内容。

**保留 PipelineEngine class 接口（外部依赖不变）：**

| 外部引用者 | 引用的接口 | 保留方式 |
|:-----------|:-----------|:---------|
| `main._ensure_engine()` | `PipelineEngine()` | 保留 class |
| `main._sm_handle_complete` | `engine.try_advance()` | 保留方法 |
| `main.handle_broadcast` | `engine.restore_pipeline_timers()` | 保留方法 |
| `main.handle_broadcast` | `engine._ensure_git_scan()` | 保留方法 |
| `main.handle_broadcast` | `engine._ensure_timeout_scanner()` | 保留方法 |
| `__main__.py` | `engine._retry_loop()` | 保留方法 |
| `__main__.py` | `engine.restore_pipeline_dispatches()` | 保留方法 |
| `scenario_matcher` | `engine.format_context()` | 保留方法 |
| `scenario_matcher` | `engine.find_archive()` | 保留方法 |
| `engine2._ensure_engine()` | `PipelineEngine()` | 保留 class |

**合并策略：**

```
新 pipeline_engine.py = engine2.py 的全部代码（已验证）
                     + PipelineEngine class（薄 wrapper 或直接委托）
                     + 旧 pipeline_engine 中 engine2 没有的功能
```

### MERGE-B：吸收旧 pipeline_engine.py 的有用功能

旧版 pipeline_engine.py 中 engine2.py 没有、但有用的功能：

| 功能 | 旧 pipeline_engine | 合并方式 |
|:-----|:-------------------|:---------|
| `format_context()` | PipelineEngine 方法 | 整合进新 engine（engine2 风格或 class 方法） |
| `_ensure_git_scan()` / `_start_git_sync_loop()` / `_pipeline_git_sync_scan()` | PipelineEngine 方法 | 保留（已在 engine2 的 `_auto_advance_pipeline` 中被调用） |
| `_ensure_timeout_scanner()` / `_start_timeout_scan_loop()` / `_pipeline_timeout_scan()` | PipelineEngine 方法 | 保留 |
| `restore_pipeline_timers()` / `restore_pipeline_dispatches()` | PipelineEngine 方法 | 保留 |
| `start()` / `stop()` 生命周期 | PipelineEngine 方法 | 保留（统一启动后台扫描） |
| `_step_sort_key()` | 静态方法 | 保留（被 `_auto_advance_pipeline` 使用） |
| `_cmd_task_update()` | PipelineEngine 方法 | 保留（被 `auto_advance` 使用） |
| `broadcast_workspace_archived()` | PipelineEngine 方法 | 保留 |
| `handle_reject()` | PipelineEngine 方法 | 用 engine2 的 `_handle_reject` 替换 |

### MERGE-C：修复 B-5 bug

B-5 的根因是 `pipeline_engine.auto_dispatch()` 有 PM fallback 链：

```python
# 旧 pipeline_engine.py L826-L833（有 bug）:
if not target_agent_id:
    if self._resolve_card_key:
        target_agent_id = self._resolve_card_key(config.PIPELINE_PM_AGENT_ID or "")
    if not target_agent_id:
        target_agent_id = config.PIPELINE_PM_AGENT_ID
```

engine2 的 `_auto_dispatch()` 无此代码，直接用：

```python
# engine2.py（已验证 ✅）:
next_step_info = next(
    (s for s in (ctx.steps or []) if s.get("name") == next_step_key), None,
)
if not next_step_info or not next_step_info.get("agent_id"):
    return False  # 找不到就返回，不发错人
```

合并后 B-5 自动修复（用 engine2 的 `_auto_dispatch` 替换旧版）。

### MERGE-D：删除 engine2.py

engine2.py 是 R137 的临时过渡文件，合并完毕后删除。

**需要检查的引用：**

| 引用源 | 引用项 | 迁移方式 |
|:-------|:-------|:---------|
| `main.py` L48 | `from .engine2 import _resolve_card_key_to_ws_id, _extract_artifact_kv` | 改为 `from .pipeline_engine import ...` |
| `scenario_matcher.py` | `from . import engine2 as _e2` | 改为 `from . import pipeline_engine as _e2` |
| `scenario_matcher.py` | `_e2._ensure_engine()`, `_e2._ensure_pipeline_manager()` | 同上 |
| `scenario_matcher.py` | `_e2._handle_hash_*()` | 同上 |

---

## 3. 文件变动清单

### 3.1 pipeline_engine.py — 完全重写

**源：** engine2.py（1,544 行） + 旧 pipeline_engine.py 的 class wrapper + 有用功能

**目标大小：** ~1,600 行

**大致结构：**

```
pipeline_engine.py
├── docstring + imports (~40 行)
├── PipelineEngine class (~1,500 行)
│   ├── __init__(...)          # 保留构造注入
│   ├── start() / stop()       # 生命周期
│   ├── 工具函数                # format_context, render_template, build_step_summary, ...
│   ├── 状态推进                # try_advance, auto_advance
│   ├── ## 命令                 # handle_hash_start/status/stop/advance/archive
│   ├── 自动调度                # auto_dispatch, auto_re_notify, retry
│   ├── 通知/驳回               # notify_pm, handle_reject
│   ├── 后台扫描                # git_sync, timeout, restore
│   └── 引用支持                # _ensure_engine, _ensure_pipeline_manager (forwarders)
├── 模块级常量/全局变量          # _ROLE_EMOJIS, _ROLE_NAMES, _URL_FIELDS
```

### 3.2 engine2.py — 删除

```bash
git rm server/ws_server/engine2.py
```

### 3.3 main.py — import 更新

```python
# 旧 L48:
from .engine2 import _resolve_card_key_to_ws_id, _extract_artifact_kv

# 新:
from .pipeline_engine import _resolve_card_key_to_ws_id, _extract_artifact_kv
```

### 3.4 scenario_matcher.py — import 更新

```python
# 旧:
from . import engine2 as _e2

# 新:
from . import pipeline_engine as _e2
```

### 3.5 __main__.py — 确认无 engine2 引用

搜索 `engine2` 在 __main__.py 中是否有引用，如有则更新。

---

## 4. 合并原则

### 4.1 编码方式

```
# engine2.py（已验证）:
def _auto_dispatch(ctx, step_num):
    ...  # 无 PM fallback ✅

# 旧 pipeline_engine.py（有 bug）:
def auto_dispatch(self, ctx, step_num):
    ...  # 有 PM fallback ❌

# 新 pipeline_engine.py:
def auto_dispatch(self, ctx, step_num):
    ...  # 用 engine2 版本替换 ✅
```

### 4.2 不做的

| 事项 | 原因 |
|:-----|:-----|
| 函数重命名 | 保持接口一致 |
| 参数签名变更 | 外部依赖不变 |
| 功能优化/重构 | 纯合并，不新增行为 |
| WS 协议代码修改 | main.py 不变 |

### 4.3 验证方法

```bash
# 无 ImportError
python3 -c "from server.ws_server import main"
python3 -c "from server.ws_server import pipeline_engine"

# 无 engine2 残留
python3 -c "from server.ws_server import engine2"  # 应报 ImportError

# 功能测试（同 R137 验收）
##start##R138-test##task=dev##steps=2
##status##R138-test
```

---

## 5. 验收标准

| # | 验收项 | 类型 | 状态 |
|:-:|:-------|:----:|:----:|
| MERGE-A | `pipeline_engine.py` 替换为 engine2.py 代码主体 | P0 | ⬜ |
| MERGE-B | 旧 pipeline_engine 的有用功能已合并（format_context, timeout scan, git scan 等） | P0 | ⬜ |
| MERGE-C | B-5 PM fallback bug 已修复（auto_dispatch 无 PM 降级） | P0 | ⬜ |
| MERGE-D | `engine2.py` 已删除，`python3 -c "from server.ws_server import engine2"` 报错 | P0 | ⬜ |
| U1 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | ⬜ |
| U2 | `python3 -c "from server.ws_server import pipeline_engine"` 无 ImportError | P0 | ⬜ |
| T1 | `##start##R138-test` 正常启动 + 派活 Step 2 | P0 | ⬜ |
| T2 | `##status##R138-test` 正常查询 | P0 | ⬜ |
| T3 | `##stop##R138-test` 正常停止 | P0 | ⬜ |
| T4 | `已完成 ✅` 自动推进正常（不再走 PM fallback） | P0 | ⬜ |
| T5 | 退回 🔄 驳回回退正常 | P0 | ⬜ |
| T6 | PM 通知正常送达 | P0 | ⬜ |
| T7 | `handle_broadcast` 非管线消息路由正常 | P0 | ⬜ |
| T8 | 规则路由 10/20/30/40/50/60/70/90 正常 | P0 | ⬜ |
| T9 | Git sync / Timeout scanner 正常启动 | P1 | ⬜ |
| T10 | `_retry_loop()` 启动正常 | P1 | ⬜ |

---

## 6. 方向决定

| 决定事项 | 选择 | 说明 |
|:---------|:-----|:------|
| 最终名称 | `pipeline_engine.py` | 保留原名，无歧义 |
| 合并方向 | engine2（已验证）吞并 pipeline_engine（精简版） | 已验证代码为主 |
| PipelineEngine class | 保留 | main.py/__main__.py/scenario_matcher 依赖 |
| `engine2.py` | 删除 | 临时名已完成使命 |
| B-5 修复方式 | 替换 auto_dispatch 为 engine2 版本 | 自动修复，无需额外编码 |

---

> **审核记录：**
> - v1.0 提交审核：[@2026-07-20]
> - 项目负责人审核意见：
> - 结论：⬜ 待审核
