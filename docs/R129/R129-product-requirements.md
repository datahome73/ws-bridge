# R129 需求文档 — 废弃代码清理（PipelineAutoStarter 退役）

> **轮次：** R129
> **类型：** 代码清理轮
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 草稿待审

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

### 2.3 文档清理

| 文件 | 改动 |
|:-----|:------|
| `docs/R119/*.md` | 移除 PAS_ENABLED=0 部署要求 |
| `docs/inbox-message-protocol.md` | 移除 PAS 相关引用 |
| `docs/TODO.md` | 移除 PAS 相关待办 |

### 2.4 不删除

| 文件 | 理由 |
|:-----|:------|
| `server/ws_server/auto_router.py` | 独立 CLI 脚本，非 server 启动依赖，不阻塞任何功能 |

---

## §3 改动范围汇总

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| 🗑️ 删除 | `server/ws_server/pipeline_auto_starter.py` | -211 |
| ✂️ 修改 | `server/ws_server/__main__.py` | -35 |
| ✂️ 修改 | `server/ws_server/pipeline_context.py` | -70 |
| ✂️ 修改 | 文档文件 (docs/R119/*.md, inbox-protocol, TODO.md) | ~-20 |
| **合计** | | **~-336 行** |

> 净删 ~336 行，零新增。纯清理轮。

---

## §4 验收标准

### CL-N: 清理验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| CL-1 | `pipeline_auto_starter.py` 文件不存在 | 功能 |
| CL-2 | `__main__.py` 中无 `PipelineAutoStarter` import 或引用 | 功能 |
| CL-3 | `__main__.py` 中无 `PAS_ENABLED` 读取或判断 | 功能 |
| CL-4 | `pipeline_context.py` 中无 `from_work_plan()` 方法 | 功能 |
| CL-5 | `pipeline_context.py` 中无 `created_by="system:pipeline_auto_starter"` 引用 | 功能 |

### RV-N: 回归验证（P0）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| RV-1 | `py_compile` 全量零错误 | 编译 |
| RV-2 | 启动后 `##start` / `##status` / `##advance` / `##archive` 全部正常 | 回归 |
| RV-3 | `_auto_dispatch` 正常派活（不受 PAS 删除影响） | 回归 |
| RV-4 | 环境变量 `PAS_ENABLED` 不再需要（不设置也不报错） | 回归 |

### DO-N: 文档同步（P1）

| 编号 | 描述 | 类型 |
|:----|:-----|:----:|
| DO-1 | `docs/R119/*.md` 中 PAS_ENABLED 部署要求已移除 | 文档 |
| DO-2 | `docs/inbox-message-protocol.md` 中 PAS 引用已移除 | 文档 |
| DO-3 | `docs/TODO.md` 中 PAS 相关项已清理 | 文档 |

---

## §5 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不改 `auto_router.py`** | 独立 CLI 脚本，不参与 server 启动，不阻塞业务 |
| ❌ | **不重构 `from_work_plan` 替代逻辑** | 当前管线创建全走 `##start` 协议，无需替代 |
| ❌ | **不删 `PAS_ENABLED` 兼容读** | 如果其他部署脚本设置了该变量，删除后不应报错——改为忽略即可 |
| ❌ | **不改 R128 正在修的代码** | `pipeline_engine.py` 中有两行注释提及 `pipeline_auto_starter.py`，注释不影响运行，清理注释是编辑性改进 |

---

## §6 验收检查表

### 文件改动清单

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| 🗑️ 删除 | `server/ws_server/pipeline_auto_starter.py` | -211 |
| ✂️ 修改 | `server/ws_server/__main__.py` | -35 |
| ✂️ 修改 | `server/ws_server/pipeline_context.py` | -70 |
| ✂️ 修改 | 文档文件 | ~-20 |
| **合计** | | **~-336 行** |

### 验收计数

| 分组 | P0 | P1 | 合计 |
|:-----|:--:|:--:|:----:|
| CL 清理验证 | 5 | — | 5 |
| RV 回归验证 | 4 | — | 4 |
| DO 文档同步 | — | 3 | 3 |
| **合计** | **9** | **3** | **12** |
