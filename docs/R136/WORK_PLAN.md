---
pipeline:
  name: "R136 — 纯提取轮：连接管理 + 看门狗 + ACK 状态机 + 超时扫描 + Git 调度 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R136/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R136/R136-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 提取方案设计
      - step: step3
        role: developer
        title: 5 模块逐批提取
      - step: step4
        role: reviewer
        title: 提取审查 + import 验证
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署归档
steps:
  - name: step2
    agent_id: ws_3f7cdd736c1c
    agent_name: 小开
    title: 提取方案设计 — 5 模块精确范围 + 接口定义
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码 — 5 模块逐批提取 + 验证
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — import 正确性 + 行为不变
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 12 项验收
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R136 工作计划 — 纯提取轮

> **版本：** v1.0
> **状态：** ✅ 已通过
> **日期：** 2026-07-20

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求文档 + 排查记录 |
| 🏗️ 架构师 | 小开 | 提取方案设计 → 编码审查 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🚢 Operations | 小爱 | 步骤 6 合 main 部署 |

---

## 提取总览

| EXT# | 目标文件 | 提取范围 | 行数 | 风险 |
|:----:|:---------|:---------|:----:|:----:|
| EXT-1 | `connection_manager.py` | auth/register/`_connections`/`_send`/`_send_to_agent` | ~200 | ⚠️ 多处 import，需小心 |
| EXT-2 | `watchdog.py` | 看门狗循环 + 告警 + escalation | ~300 | 🟢 内聚度高 |
| EXT-3 | `ack_machine.py` | ACK 超时检测 + 状态格式化 | ~50 | 🟢 独立无依赖 |
| EXT-4 | `pipeline_timeout.py` | 超时扫描定时器 | ~60 | 🟢 边界清晰 |
| EXT-5 | `git_sync_scheduler.py` | Git 同步调度循环 | ~30 | 🟢 最独立 |
| **合计** | | **main.py 3,092 → ~2,450 行** | **~640** | |

---

## 提取原则

### 编码方式

```python
# 原 main.py L140-L148:
async def _send(ws, data: dict) -> None:
    ...

# 提取后 connection_manager.py:
async def _send(ws, data: dict) -> None:
    ...  # 完全相同的代码

# 原位置 main.py 替换为:
from .connection_manager import _send
```

### 提取顺序（按风险从低到高）

1. **EXT-5 Git 调度** → 最独立，先提取热身
2. **EXT-4 超时扫描** → 依赖 `_send_to_agent` 回调，但可以通过函数引用传入
3. **EXT-3 ACK 状态机** → 纯状态操作
4. **EXT-2 看门狗** → 较大，内部无外部依赖
5. **EXT-1 连接管理** → 被多方引用，最后提取确保所有 import 一次性到位

### 验证方法

每提取一个模块后，运行：

```bash
python3 -c "from server.ws_server import main"
python3 -c "from server.ws_server.connection_manager import handle_auth"
```

如有 ImportError，立即修正再继续下一步。

### 不做的事项

- 不改函数名、不改参数签名
- 不改 `state._*` 全局变量引用方式
- 不合并同类函数、不重构
- 提取后 `main.py` 的 import 行使用与原函数名相同的名字（保持引用者不变）

---

## 注意事项

1. 提取后 `main.py` 仍然保有所有函数名（通过 import），所以 `__main__.py` / `scenario_matcher.py` / `pipeline_engine.py` 的 import 不需要改
2. `handle_auth` 在 `__main__.py` 中被 import，提取后路径变为 `from .connection_manager import handle_auth`，需同步修改 `__main__.py` 的 import 语句
3. `_send_to_agent` 通过构造注入进 `PipelineEngine`，提取后 import 路径变化但注入点不变
4. `handler()` 函数（L2731，ws_handler 连接管理部分）中有 `_connections.setdefault(agent_id, set()).add(ws)` 代码，这部分与 `connection_manager` 的 `_connections` 变量相关联——提取后要确保两者指向同一个 dict 实例
5. 参考：`server/ws_server/README.md`
