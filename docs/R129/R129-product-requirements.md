# R129 需求文档 — 废弃代码清理 + Bug 修复（运行中发现）

> **轮次：** R129
> **类型：** 代码清理轮 + Bug 修复
> **版本：** v1.2
> **日期：** 2026-07-19
> **状态：** 📝 已修订

---

## §1 背景与现状

### 历史

`PipelineAutoStarter`（PAS）是 R110 引入的 Git 感知管线自动启动器。设计目标是：定期 `git fetch` → 扫描 `docs/` 中新 R{N}/WORK_PLAN.md → 自动创建管线并派活。

### 当前状态

| 指标 | 值 |
|:-----|:----|
| 代码行数 | 211 行（`pipeline_auto_starter.py`） |
| 启动关联 | 35 行（`__main__.py` import + init + PAS_ENABLED 逻辑） |
| 数据层关联 | ~70 行（`pipeline_context.py` 的 `from_work_plan()` 方法） |
| 启用状态 | **已关闭**（`PAS_ENABLED=0`，自 R119 起） |
| 实际使用 | 从未成功投产（R111 文档已标记「废弃，不碰」） |

从 R119 起，管线启动全部改用 `##start` 协议由 PM 手动触发。PAS 已连续多轮处于「禁用但未删除」状态。

### 为什么现在清理

1. **自动管线已成熟** — 经理接管调度后，`##start` + `_auto_dispatch` 是全自动管线的标准入口，PAS 的 Git poll 路径已无存在价值
2. **减少部署配置项** — `PAS_ENABLED=0` 是生产部署必加的环境变量，去掉后减少一项部署要求
3. **消除误导** — 代码存在但已废弃，新开发者看到 `PAS_ENABLED` 会困惑是否该启用
4. `auto_router.py`（750 行，独立 CLI 脚本）已自 R89 起标记为 `[DISABLED]`，不是 server 的启动依赖，本轮不处理

---

## §2 清理范围

### 2.1 删除文件

| 文件 | 行数 | 说明 |
|:-----|:----:|:------|
| `server/ws_server/pipeline_auto_starter.py` | 211 | 整个文件删除 |

### 2.2 修改文件

| 文件 | 改动 | 约行数 |
|:-----|:------|:------:|
| `server/ws_server/__main__.py` | 删除 import（L18）+ PAS init 块（L796-835）+ `PAS_ENABLED` 读取 | **-35** |
| `server/ws_server/pipeline_context.py` | 删除 `from_work_plan()` 方法（L647-715）和模块级入口（L433） | **-70** |

### 文档清理

| 文件 | 改动 |
|:-----|:------|
| `docs/inbox-message-protocol.md` | 移除 PAS 相关引用 |
| `docs/TODO.md` | 移除 PAS 相关待办 |

> **历史轮次文档不碰** — `docs/R119/*.md` 等已归档轮次保留原样，不进 git 修改历史。

### 2.4 不删除

| ❌ | **不改 R128 正在修的代码** | `pipeline_engine.py` 中有两行注释提及 `pipeline_auto_starter.py`，注释不影响运行，清理注释是编辑性改进 |

---

## §7 运行中发现的问题修复

> 以下问题在 R129 管线运行 Step 1→2 推进过程中发现（2026-07-19），优先在本轮修复。

### B-5: `{round}` 模板占位符在 PipelineEngine.auto_dispatch 中未替换

**现象：** 派活消息中 `{round}` 字面量原样输出（如 `💻 {round} Step 3 — 编码实现`），未替换为 `R129`。Step 1 由旧 `_auto_dispatch`（`_render_template`）派发正常，但 Step 2+ 由新 `PipelineEngine.auto_dispatch`（`self.render_template`）派发，新旧 `render_template` 占位符不兼容。

**修复范围：** `server/ws_server/pipeline_engine.py` +1 行

| 函数 | 位置 | 缺的占位符 |
|:-----|:-----|:----------|
| `PipelineEngine.render_template()` | `pipeline_engine.py:211` | 缺 `{round}` → `ctx.round_name` 别名 |

### B-6: 派活消息显示 2 遍（B-1 复发）

**现象：** `系统 → 小开` 的派活消息在对话中出现 2 次。

**根因：** `_send_to_agent()`（`main.py:2516`）既通过 WebSocket 直发到目标 agent 的实时连接，又通过 `ms.save_message()` 持久化到 DB。当目标 agent 同时有离线消息回放时（例如重连后），会收到两条同样的消息——一条来自实时 WS，一条来自 DB 回放。

**修复范围：** `server/ws_server/main.py` 约 +5 行

**方案：** `_send_to_agent()` 保存到 DB 前检查该 `channel` 最近 1 秒内是否有相同 `content` 的消息，有则跳过 `ms.save_message()`，避免离线重放引入重复。

### B-7: `##start`/`##status`/`##advance` 等命令静默无响应

**现象：** 临时 bot 发送 `##status##R129`、`##start##R{N}` 到 `_inbox:server` 无任何回复（不报错、不回显）。`##help` 正常工作（因 `len(parts) < 3` 提前返回）。

**根因：** `scenario_matcher.py` `handle_hash_cmd()` 中：
```python
from .pipeline_engine import PipelineEngine
_engine: PipelineEngine = None  # type: ignore
```
局部变量 `_engine = None` 覆盖了 `main.py` 注入的模块级 `_engine`（`_sm._engine = _ensure_engine()`），导致所有非 `##help` 命令的 `if _engine else False` 始终为 False。

**修复范围：** `server/ws_server/scenario_matcher.py` -2 行 / +2 行

**方案：** 改回 `from . import main as _main; await _main._handle_hash_*(...)` 模式，不依赖局部变量。

---

## §8 改动范围汇总（更新后）

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| 🗑️ 删除 | `server/ws_server/pipeline_auto_starter.py` | -211 |
| ✂️ 修改 | `server/ws_server/__main__.py` | -35 |
| ✂️ 修改 | `server/ws_server/pipeline_context.py` | -70 |
| ✂️ 修改 | 文档（inbox-protocol.md, TODO.md） | ~-10 |
| 🐛 修复 B-5 | `server/ws_server/pipeline_engine.py` | +1 |
| 🐛 修复 B-6 | `server/ws_server/main.py` | ~+5 |
| 🐛 修复 B-7 | `server/ws_server/scenario_matcher.py` | ~±3 |
| **合计** | | **~-317 行** |

> 净删 ~326 行 + 增 ~9 行 = **净减 ~317 行**。

---

## §9 验收标准（更新）

### CL-N: 清理验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| CL-1 | `pipeline_auto_starter.py` 文件不存在 | 功能 |
| CL-2 | `__main__.py` 中无 `PipelineAutoStarter` import 或引用 | 功能 |
| CL-3 | `__main__.py` 中无 `PAS_ENABLED` 读取或判断 | 功能 |
| CL-4 | `pipeline_context.py` 中无 `from_work_plan()` 方法 | 功能 |
| CL-5 | `pipeline_context.py` 中无 `created_by="system:pipeline_auto_starter"` 引用 | 功能 |

### FX-N: 修复验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| **FX-1** | 派活消息中 `{round}` 被正确替换为轮次名（如 `R129`） | 功能 |
| **FX-2** | 派活消息不重复出现（`_send_to_agent` 不产生 DB 回放重复） | 功能 |
| **FX-3** | `##start` / `##status` / `##advance` / `##archive` / `##stop` 全部正常响应 | 功能 |

### RV-N: 回归验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| RV-1 | `py_compile` 全量零错误 | 编译 |
| RV-2 | `_auto_dispatch` 正常派活（不受 PAS 删除影响） | 回归 |
| RV-3 | 环境变量 `PAS_ENABLED` 不再需要（不设置也不报错） | 回归 |
| RV-4 | `_send_to_agent` 离线消息回放不因去重而丢消息（低概率消息在 1s 内不同 content 不会误去重） | 回归 |

### DO-N: 文档同步（P1）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| DO-1 | `docs/inbox-message-protocol.md` 中 PAS 引用已移除 | 文档 |
| DO-2 | `docs/TODO.md` 中 PAS 相关项已清理 | 文档 |
| DO-3 | 无 PAS 相关环境变量残留文档 | 文档 |

---

## §10 验收检查表（更新后）

### 文件改动清单

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| 🗑️ 删除 | `server/ws_server/pipeline_auto_starter.py` | -211 |
| ✂️ 修改 | `server/ws_server/__main__.py` | -35 |
| ✂️ 修改 | `server/ws_server/pipeline_context.py` | -70 |
| ✂️ 修改 | 文档（inbox-protocol.md, TODO.md） | ~-10 |
| 🐛 修复 B-5 | `server/ws_server/pipeline_engine.py` | +1 |
| 🐛 修复 B-6 | `server/ws_server/main.py` | ~+5 |
| 🐛 修复 B-7 | `server/ws_server/scenario_matcher.py` | ~±3 |
| **合计** | | **~-317 行** |

### 验收计数

| 分组 | P0 | P1 | 合计 |
|:-----|:--:|:--:|:----:|
| CL 清理验证 | 5 | — | 5 |
| FX 修复验证 | 3 | — | 3 |
| RV 回归验证 | 4 | — | 4 |
| DO 文档同步 | — | 3 | 3 |
| **合计** | **12** | **3** | **15** |
