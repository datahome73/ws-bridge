---
pipeline:
  name: "R91 自动化管线可用性验证 — 根治 workspace 阻塞 + AutoRouter 实测 🔧"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R91/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R91/R91-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 技术方案
      - step: step3
        role: developer
        title: 编码实现
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署归档
  steps:
    step2:
      role: architect
      title: 技术方案
    step3:
      role: developer
      title: 编码实现
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署归档
  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "方案设计：max_per_person 瓶颈 + AutoRouter 全流程验证"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码：workspace.py 上限 + AutoRouter 全自动管线启停"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 workspace 上限变更 + AutoRouter 管线逻辑"
      qa:
        mention_keyword: "qa;测试"
        rules: "验收测试：AutoRouter 全自动管线完整闭环"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + docker build + 重启 AutoRouter + 启动管线实测"
---

# R91 产品需求 — 自动化管线可用性验证 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R90 AutoRouter 坑位修补已部署 ✅（v2.56, main `6dbaad6`）
> **改动范围：** `server/workspace.py` + `server/handler.py`

---

## 1. 问题背景

### 1.1 现状

R88 → R89 → R90 三次迭代实现了 AutoRouter 自动派活服务和 3 个坑位修补：
- ✅ R88: PipelineAutoRouter 独立服务创建
- ✅ R89: `_send_inbox()` payload 补全 + Step 超时检测
- ✅ R90: AutoRouter 监听 `_admin` 频道 + 工作区失败通知 + `AR_STEP_TIMEOUT` 环境变量

**但 R89 和 R90 的实际管线都未能走通 AutoRouter 自动模式**，全部回退到 inbox 手动协调。

### 1.2 根因：Workspace 创建瓶颈 `max_per_person = 1`

`server/workspace.py` L267 定义：

```python
max_per_person = 1  # configurable later
if active_count >= max_per_person:
    return None
```

| 问题 | 说明 |
|:-----|:------|
| 🔴 限制过紧 | 每人只能有 **1 个活跃工作室**。PM 小谷执行 `!pipeline_start R{NN}` 时，若已有活跃工作室，创建直接返回 None |
| 🟡 无自动清理 | 旧管线完成或异常中断后，工作室停留在 ACTIVE 状态，新管线无法创建 |
| 🟡 错误信息模糊 | handler.py 报「可能已存在，或管理员名下活跃工作区过多」，无法区分原因 |
| 🟡 无优雅降级 | 创建失败后 `_cmd_pipeline_start` 仍返回「✅ 管线已启动」，管线处于孤儿状态 |

**实战证据：**
- R89: `!pipeline_start` 返回 `❌ 创建失败：R89-dev 可能已存在，或管理员名下活跃工作区过多`
- R90: 同上（未修复 workspace 层）
- 所有管线全部回退 inbox 手动协调

### 1.3 连锁影响

```
max_per_person=1
    ↓
workspace 创建失败
    ↓
_PIPELINE_STATE 中未正确注册
    ↓
!pipeline_status R{N} 返回"管线不存在"
    ↓
AutoRouter 历史（R89）收不到信号 → 自动接力不触发
    ↓
PM 必须 inbox 手动协调全流程
```

R90 🅰️ 已修复 AutoRouter 监听 `_admin` 频道。但 workspace 创建失败导致 `_PIPELINE_STATE` 不完整，AutoRouter 即使收到 `_admin` 的管线启动信号，也无法正确恢复/查询进度。

---

## 2. 方案设计

### 2.1 改动范围

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `server/workspace.py` | 🅰️ `max_per_person` 提高 + 可配置化（`MAX_ACTIVE_WORKSPACES`） | ~+5 行 |
| `server/handler.py` | 🅱️ 创建失败错误信息细化（区分重名/超限） | ~+15 行 |
| **合计** | **2 个改动点** | **~+20 行净增** |

### 2.2 🅰️ 提升 workspace 上限 + 可配置化

**原理：** 将 `max_per_person = 1` 提高为可配置值，默认 3，保证多轮管线迭代互不阻塞。

```python
# Before (workspace.py L267)
max_per_person = 1  # configurable later

# After
# R91: 可配置上限，默认 3 个活跃工作室
from server import config as srv_config
_default_max = getattr(srv_config, "MAX_ACTIVE_WORKSPACES", 3)
max_per_person = _default_max
```

**替换方式 B（更轻量）：** 如果不想加 config 依赖，可以用 `os.environ.get("MAX_ACTIVE_WORKSPACES", 3)`，用 int() 转换。

**考虑：** `_cmd_close_workspace` 是否正常工作？如果旧工作室不能被 close，提升上限只是权宜之计。需检查 `close_workspace` 是否将状态正确设为非 ACTIVE。

### 2.3 🅱️ 创建失败错误信息细化

**原理：** handler.py L693 的失败信息改为区分具体原因。

**改动点：** `_cmd_create_workspace` (handler.py ~L680-710) 中，create_workspace 返回 None 后检查具体原因：

```python
result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
if not result:
    # R91 🅱️: 区分超限 vs 重名
    name_lower = ws_name.lower()
    name_id = f"ws_{name_lower}-dev"
    existing_ws = ws_mod.get_workspace(name_id)
    if existing_ws:
        return f"❌ 创建失败：工作室「{ws_name}」已存在。使用 --workspace-id {name_id} 附着或先 !close_workspace {name_id}"
    # 检查活跃工作区数量
    active_count = sum(
        1 for w in ws_mod.get_all_workspaces()
        if w.owner_id == sender_id and w.state == ws_mod.WorkspaceState.ACTIVE
    )
    max_ws = 3  # 与 DEFAULT_MAX_ACTIVE_WORKSPACES 保持一致
    return f"❌ 创建失败：管理者名下已有 {active_count}/{max_ws} 活跃工作室。请先 !close_workspace 关闭旧工作室"
```

### 2.4 AutoRouter 全自动管线验证（非代码改动）

R90 修复后，部署完 R91 需要**实际验证一次 AutoRouter 全自动管线**：

| 验证项 | 方法 | 预期 |
|:-------|:-----|:------|
| ⓐ AutoRouter 收到 `_admin` 信号 | `!pipeline_start R91-test` → 检查日志 | `_on_pipeline_ready(R91-test)` 被调用 |
| ⓑ AutoRouter 派活 Step 2 | 小开 inbox 收到任务 | ✅ 任务送达 |
| ⓒ Step 完成自动接力 | 小开发 `✅ 完成` → 爱泰 inbox 收到任务 | Step 2→3 自动 |
| ⓓ 全链路闭环 | 6 Step 全部自动接力 | PM 收件箱收到 `🏁 全部完成` |
| ⓔ Workspace 创建成功 | `!list_workspaces` | R91-test 工作室 active |

---

## 3. 验收清单

| # | 内容 | 验证方法 |
|:-:|:-----|:---------|
| 🅰️-1 | `workspace.py` 的 `max_per_person` 从硬编码 1 改为可配置，默认 3 | 创建第 2 个工作室应成功 |
| 🅰️-2 | 设 `MAX_ACTIVE_WORKSPACES=5` → 可创建 5 个工作室 | 环境变量生效 |
| 🅰️-3 | 未设配置项时默认行为宽松（非 1） | 第 2 个工作室创建成功 |
| 🅱️-1 | 超限时错误信息包含「活跃工作区过多」| 超限场景测试 |
| 🅱️-2 | 重名时错误信息包含「已存在」| 重名场景测试 |
| 🅲-1 | AutoRouter 收到 _admin 的管线启动信号 | 集成测试 |
| 🅲-2 | AutoRouter Step 2→3 自动接力 | 全流程验证 |
| 🅲-3 | 全 6 Step 闭环，PM 收 🏁 通知 | 全流程验证 |
| 🅲-4 | 工作区创建成功 | `!list_workspaces` 查询 |

---

## 4. R91 管线 Step 定义

```
Step 1: PM — 需求文档 + WORK_PLAN → 推 dev
Step 2: Arch — 技术方案（workspace 上限 + 错误细化设计）
Step 3: Dev — 编码实现（workspace.py + handler.py ~+20 行）
Step 4: Review — 代码审查（重点：上限修改安全性）
Step 5: QA — 测试验证（9 项验收）
Step 6: Ops — 合并 main + **启动 AutoRouter 全自动管线验证**
```

---

## 5. 风险与缓解

| 风险 | 等级 | 缓解 |
|:-----|:----:|:------|
| `max_per_person=3` 仍不够 | 🟢 | `MAX_ACTIVE_WORKSPACES` 可配置调整 |
| 旧工作室堆积无自动清理 | 🟡 | 建议后续轮次加归档逻辑（管线完成自动 close） |
| AutoRouter 仍有信号 gap | 🟡 | 三级递进保底 |
| handler.py 返回值字符串解析耦合 | 🟢 | 仅改 _cmd_create_workspace 的返回值，调用者不变 |
