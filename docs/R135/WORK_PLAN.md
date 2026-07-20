---
pipeline:
  name: "R135 — handle_broadcast 死代码清理 + 频道体系精简 🧹"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R135/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R135/R135-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 清理方案设计
      - step: step3
        role: developer
        title: 批量死代码删除
      - step: step4
        role: reviewer
        title: 删除审查 + import 检查
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
    title: 清理方案设计
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码 — 12 项清理（A-L）+ 验收
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — 删除检验 + import 残留检验
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 18 项验收
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R135 工作计划 — 死代码清理 + 频道体系精简

> **版本：** v1.0
> **状态：** 📝 草稿
> **日期：** 2026-07-20

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求文档 + 排查记录 |
| 🏗️ 架构师 | 小开 | 方案设计 → 编码审查 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🦸 项目管理 | — | 经理负责管线调度，不参与具体步骤 |

---

## 清理总览

| CLN# | 文件 | 清理范围 | 行数 | 优先级 |
|:----:|:----|:---------|:----:|:-----:|
| CLN-1 | `main.py` | `_admin` 频道 intercept + 辅助函数 | ~25 | P0 |
| CLN-2 | `main.py` | 未注册 bot 保护 | ~3 | P0 |
| CLN-3 | `main.py` + `state.py` | 速率限制函数 + state 变量 | ~35 | P0 |
| CLN-4 | `main.py` + `state.py` | 全局消息过滤 + state 变量 | ~20 | P0 |
| CLN-5 | `main.py` | 用户角色/权限 + `_can_broadcast` | ~50 | P0 |
| CLN-6 | `main.py` + `state.py` | Rollcall + ACK 检测 + state 变量 | ~25 | P0 |
| CLN-7 | `main.py` + `state.py` | 频道解析/Lobby暂停/`_can_broadcast`/大厅前缀路由 | ~95 | P0 |
| CLN-8 | `main.py` | Registration 通道投递 | ~6 | P0 |
| CLN-9 | `main.py` + `state.py` | 统一广播 + 离线队列 + state 变量 | ~90 | P0 |
| CLN-10 | `main.py` + `state.py` | ACK 交付统计 + 辅助函数 | ~60 | P0 |
| CLN-11 | `workspace.py` | 精简：删除审批/关闭/归档/管理员函数 | ~200 | P1 |
| CLN-12 | `message_store.py` | 精简：删除 3 个全局查询函数 | ~60 | P1 |
| **合计** | | | **~670** | |

---

## 开发步骤

### Step 2 — 清理方案 🏗️ 架构师（小开）

产出：`docs/R135/R135-tech-plan.md`

基于需求文档和 `server/ws_server/README.md` §4 分析，设计：
- 每个 CLN 的精确删除范围（行号 + 函数名）
- import 调整方案
- state.py 变量清理清单
- 清理后 `handle_broadcast` 预期代码结构

### Step 3 — 编码 💻 开发工程师（爱泰）

按 CLN 顺序逐批删除。推荐顺序：
1. **Batch A**（CLN-1 ~ CLN-4）：`_admin`、注册、限速、过滤 — 独立无依赖
2. **Batch B**（CLN-5 ~ CLN-6）：角色权限、Rollcall — 需注意交叉引用
3. **Batch C**（CLN-7 ~ CLN-10）：大厅、注册投递、广播、ACK — 最大批 ~250 行
4. **Batch D**（CLN-11 ~ CLN-12）：workspace.py + message_store.py — 纯删除，零风险

编码原则：
- **只删不改**：不重构正常代码，不移动函数位置
- **每删除一段后立即 `python3 -c "from server.ws_server import main"` 验证**
- 删除的函数如果有 import，一并清理
- state.py 中被引用的变量，确认无其他模块引用后再删除

### Step 4 — 代码审查 🔍 审查工程师（小周）

审查重点：
- 是否有残留的已删除函数 import（特别注意 `__main__.py` 中的 import）
- 是否有在其他文件中使用的已删除函数/变量
- `_connections` 相关引用是否完整（这是最核心的状态）

### Step 5 — 测试验证 🦐 测试工程师（泰虾）

验证项目（需求文档 §4 验收标准 18 项）：
- P0 类（14 项）：清理完整性 + import 验证 + 4 个核心功能点
- P1 类（4 项）：workspace.py/message_store.py 精简

### Step 6 — 合 main + 部署 🚢 Operations（小爱）

---

## 注意事项

1. **只删不改**：R135 是纯删除轮，不要移动或重构正常代码。函数提取/类提取留 R136。
2. **state.py 谨慎**：先确认变量在其他模块的引用，再用 `search_files` 全网搜索后删除。
3. **`send_str`/`send` 二选一模式**：这是已知的重复模式（~15 处），但 R135 **不修复**，留 R136。
4. `__main__.py` 中的 `from .main import xxx` 需同步清理。
5. 清理后 `handle_broadcast` 预期约 110 行（仅惰性启动 + `_inbox:server` return + `_inbox:{agent_id}` 单播）。
6. 参考：`server/ws_server/README.md` §4.2 死代码汇总表。
