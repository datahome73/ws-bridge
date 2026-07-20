---
pipeline:
  name: "R137 — 引擎分拆轮：main.py 管线逻辑迁入 engine2.py 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R137/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R137/R137-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: engine2 接口 + 迁移方案设计
      - step: step3
        role: developer
        title: engine2.py 创建 + 路由切换 + main.py 清理
      - step: step4
        role: reviewer
        title: 代码审查 — import 正确性 + 行为不变
      - step: step5
        role: qa
        title: 测试验证 — 10 项验收
      - step: step6
        role: operations
        title: 合并部署归档
steps:
  - name: step2
    agent_id: ws_3f7cdd736c1c
    agent_name: 小开
    title: 技术方案 — engine2 接口定义 + 迁移清单 + 循环依赖规避方案
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码 — engine2.py 创建 + scenario_matcher 路由切换 + main.py 管线代码删除
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — import 正确性 + 无循环依赖 + 功能不变
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 10 项验收标准（P0 级 9 项 + P1 级 1 项）
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R137 工作计划 — 引擎分拆轮

> **版本：** v1.0
> **状态：** ⬜ 待审核
> **日期：** 2026-07-20

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求文档 + 排查记录 |
| 🏗️ 架构师 | 小开 | 技术方案设计 → 编码审查 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🚢 Operations | 小爱 | 步骤 6 合 main 部署 |

---

## 迁移总览

| EXT# | 操作 | 目标 | 行数 | 风险 |
|:----:|:-----|:-----|:----:|:----:|
| EXT-A | 创建 engine2.py，迁入管线代码 | `engine2.py`（新建） | ~1,200 迁入 | ⚠️ 大文件搬移，注意遗漏 |
| EXT-B | scenario_matcher 路由改指 engine2 | `scenario_matcher.py` | ~6 行改动 | 🟢 简单 import 替换 |
| EXT-C | main.py 删除管线代码 | `main.py` | 2,180 → ~800 行 | ⚠️ 确保不误删 WS 协议 |
| **合计** | | **main.py 2,180 → ~800 行** | **~1,200 搬走** | |

---

## 迁移原则

### 编码方式

```python
# 原 main.py L1602-L1723:
async def _handle_hash_start(round_name, kv, agent_id, ws) -> bool:
    ...  # 完整 122 行代码

# 提取后 engine2.py:
async def _handle_hash_start(round_name, kv, agent_id, ws) -> bool:
    ...  # 完全相同代码，零改动

# 原位置 main.py:
删除该函数定义
```

### 迁移顺序

1. **EXT-A** — 创建 engine2.py，逐组搬入 A1~A7 所有函数
2. **EXT-B** — scenario_matcher 路由切换（`from . import main` → `from . import engine2`）
3. **EXT-C** — main.py 删除已迁移的管线代码
4. 每步后执行 `python3 -c "from server.ws_server import main"` 和 `python3 -c "from server.ws_server import engine2"` 验证

### 验证方法

```bash
# 无 ImportError
python3 -c "from server.ws_server import main"
python3 -c "from server.ws_server import engine2"

# 功能验证（依赖完整的运行环境）
##start##R137-test##task=dev##steps=2
##status##R137-test
##stop##R137-test
```

### 循环依赖规避

engine2.py 需要调用 `_ensure_pipeline_manager()` 和 `_ensure_engine()`（定义在 main.py），采用 **函数体内 lazy import**：

```python
# engine2.py — 需要 _ensure_pipeline_manager 的函数内：
def _try_advance_pipeline(content, agent_id):
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    ...
```

这样 main.py → engine2.py 的模块级 import 不会触发 engine2.py → main.py 的模块级反引，避免循环依赖。

### 不做的

- 不改函数名、不改参数签名
- 不改 `state._*` 全局变量引用方式
- 不合并同类函数、不重构
- `pipeline_engine.py` 本轮不动（两套并行）

---

## 注意事项

1. **大文件搬移**：~1,200 行从 main.py 搬到 engine2.py，注意不要遗漏任何函数。建议逐组搬（A1→A7），每搬一组验证一次
2. **`_ensure_pipeline_manager()`** 保留在 main.py，engine2 用 lazy import 引用。Lazy import 在函数体内，不在模块级
3. **`_ensure_engine()`** 保留在 main.py，engine2 用 lazy import 引用
4. **`_connections`** 在 engine2 的若干工具函数中引用，通过 `from .connection_manager import _connections` 直接引用（connection_manager 是 R136 已提取的模块）
5. **`_restore_pipeline_timers`** 和 `_restore_pipeline_dispatches` 被 `handle_broadcast` 调用，搬迁后 main.py 通过 `from .engine2 import _restore_pipeline_timers` 引用
6. **scenario_matcher.py** 中 `_format_pipeline_status` 等函数引用 `_main._ensure_engine()` / `_main._ensure_pipeline_manager()`，路由切换后改为引用 `_e2` 版本
7. 参考：`server/ws_server/README.md`
