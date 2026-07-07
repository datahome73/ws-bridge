# R50 开发计划

> **版本：** v0.1 ✅（项目负责人审核通过）
> **状态：** ✅ **已完成 — R50 归档**
> **编制人：** 🧐 PM
> **日期：** 2026-06-28
> **基于需求：** [R50-product-requirements.md v0.1 ✅](./R50-product-requirements.md)

---

## 一、轮次概览

| 维度 | 内容 |
|:----|:------|
| **轮次** | R50 |
| **需求文档** | 🔗 [R50-product-requirements.md v0.1 ✅](./R50-product-requirements.md) |
| **本轮改动范围** | 仅第①类（服务器代码 `server/handler.py`） |
| **改动类型** | 管线自动化补全（频道切换 + 过渡命令） |

---

## 二、方向分解 & 验收对照

### 方向 B — 过渡期频道切换命令（先开发，自举驱动管线）

先开发方向 B 的 `!pipeline_activate` 和 `!step_handoff` 两条 admin 命令。开发完成后即可在 dev 容器中使用，驱动 R50 管线自己的流转。同时提取 `_switch_agent_channel()` 函数，供方向 A 复用。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| B-1 | 提取 `_switch_agent_channel(agent_id, target_ch)` 独立函数（从 R37 MSG_SET_ACTIVE_CHANNEL 代码段提取） | `server/handler.py` | ~15 行 |
| B-2 | 注册 `!pipeline_activate` 命令到 `_ADMIN_COMMANDS`（min_role=3），handler 读取 _PIPELINE_STATE → 获取 ws_id → 获取所有角色 agent_id → 逐个调 `_switch_agent_channel` | `server/handler.py` | ~25 行 |
| B-3 | 注册 `!step_handoff` 命令到 `_ADMIN_COMMANDS`（min_role=3），handler 读取 _PIPELINE_STATE → 获取当前 Step → 获取下一角色 agent_id → 调 `_switch_agent_channel` | `server/handler.py` | ~20 行 |
| B-4 | 两条命令的边界处理：无活跃管线→返回 `❌`，工作区不存在→返回 `❌`，角色找不到→返回明确信息 | `server/handler.py` | ~10 行 |
| B-5 | 命令返回执行结果（已切换人数 / 错误信息） | `server/handler.py` | ~5 行 |

**验收标准覆盖：** B-1 ~ B-8

---

### 方向 A — Step 交接自动切活跃频道（复用 B 的函数）

方向 B 的 `_switch_agent_channel` 函数就位后，在 `!step_complete` 和 `!rollcall_next` 的下一角色指派路径中挂载自动调用。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| A-1 | 在 `_cmd_step_complete` 的下一角色指派代码段（≈行 1290-1320）中，插入 `_switch_agent_channel(next_agent_id, ws_id)` 调用 | `server/handler.py` | ~5 行 |
| A-2 | 在 `_cmd_rollcall_next` 的点名代码段中，插入 `_switch_agent_channel(target_agent_id, ws_id)` 调用 | `server/handler.py` | ~5 行 |
| A-3 | 频道切换后发文本跟进通知 | `server/handler.py` | ~3 行 |
| A-4 | 仅活跃管线期间的点名触发切换，非管线普通点名不触发 | `server/handler.py` | ~3 行 |

**验收标准覆盖：** A-1 ~ A-7

---

### 开发顺序

```
B-1 (提取 _switch_agent_channel) → B-2 + B-3 (注册命令) → B-4 + B-5 (边界处理)
  ↓ 开发完成，方向 B 可用 ↓
R50 管线靠 !pipeline_activate + !step_handoff 自举驱动
  ↓
A-1 + A-2 (挂载到 step_complete/rollcall_next) → A-3 + A-4 (通知/条件守卫)
  ↓ 方向 A 开发完成 ↓
整合测试：完整跑一轮管线，验证自动切频道
```

---

## 三、角色分工

| 角色 | 人员 | 职责 | 方向 |
|:----|:----|:-----|:----:|
| 🏗️ 架构师 | arch-bot | 技术方案编写 + 工作室讨论定稿 | 全部 |
| 💻 开发工程师 | dev-bot | B-1~B-5 编码（过渡命令）→ A-1~A-4 编码（自动切换） | A/B |
| 🔍 审查工程师 | review-bot | 代码审查 | 全部 |
| 🦐 测试工程师 | qa-bot | dev 容器部署 + 执行验收测试 | 全部 |
| 🧐 PM | pm-bot | 需求文档 + WORK_PLAN + 进度跟踪 | 全部 |
| 🦸 管理员 | admin-bot | 合并 dev→main 部署生产 | 全部 |

---

## 四、管线步骤

### 🔶 前置决策区

| Step | 名称 | 状态 | 负责人 | 产出 |
|:----:|:-----|:----:|:------|:-----|
| A | 需求文档 | ✅ **已审核** | 🧐 PM | `R50-product-requirements.md` v0.1 ✅ |
| B | 🆕 工作计划 | ⏳ 待审核 | 🧐 PM | 此文件，待项目负责人审核 |

> 前置决策区全部 ✅ 通过后，PM 触发 `!pipeline_start R50 --from step2` 进入自动化管线。

### 🟢 自动化管线（6 步）

| Step | 名称 | 状态 | 负责人 | 产出 | 说明 |
|:----:|:-----|:----:|:------|:-----|:-----|
| 1 | 🆕 管线启动 | ⏳ | 🦸 admin-bot | 工作室 R50-dev 已就绪 | 触发后 PM 请 admin-bot 执行 `!pipeline_activate R50` 全员切频道 |
| 2 | 🏗️ 技术方案 | ✅ | 🏗️ arch-bot | `R50-tech-plan.md` | commit `fbfd902` |
| 3 | 💻 编码（方向 B） | ⏳ | 💻 dev-bot | B-1~B-5 编码推 dev | 先做方向 B（过渡命令），使管线可自驱动 |
| 4 | 🔍 代码审查 | ⏳ | 🔍 review-bot | `R50-code-review.md` | 方向 B 审查 |
| 5 | 💻 编码（方向 A） | ⏳ | 💻 dev-bot | A-1~A-4 编码推 dev | 方向 B 部署后做方向 A |
| 6 | 🔍 代码审查 | ⏳ | 🔍 review-bot | 补充审查 | 方向 A 审查 |
| 7 | 🦐 测试验证 | ✅ | 🦐 qa-bot | dev 部署 + 全量验收 | 21/21 ✅ |
| 8 | 🦸 合并部署 | ✅ | 🦸 admin-bot （项目管理） | 合并 dev→main (425d0e4) + 生产部署 ws-bridge:r50 | ✅ 7 agents 在线 |

### R50 管线自举说明

R50 管线自身是方向 B 的第一个使用者：

```
管线 Step 3（方向 B 编码）：dev 完成 B-1~B-5
  ↓
推 dev → !step_complete Step3 --output sha
  ↓
PM 请 admin-bot 执行 !step_handoff R50（切 review 频道到工作室）
  ↓
review 收到通知 → 开始审查方向 B
```

这验证了：
1. 方向 B 命令本身可用 ✅
2. 过渡期管线靠命令驱动 ✅
3. 方向 A 开发完成后可对比「手动切」vs「自动切」的行为一致性 ✅

---

## 五、验收清单

| 方向 | 验收项 | 优先级 | 测试方法 |
|:----:|:------|:-----:|:---------|
| A | A-1: `!step_complete` 自动发 MSG_SET_ACTIVE_CHANNEL | 🔴 P0 | Step 7 端到端跑管线验证 |
| A | A-2: 目标频道为管线工作室 ws_id | 🔴 P0 | 检查 agent 活跃频道 |
| A | A-3: `persistence.set_agent_channel()` 持久化 | 🔴 P0 | 重连后验证频道 |
| A | A-4: `!rollcall_next` 也触发 | 🟡 P1 | 手动点名后验证 |
| A | A-5: 仅活跃管线期间触发 | 🟡 P1 | 非管线点名不受影响 |
| A | A-6: 切换后发文本跟进通知 | 🟡 P1 | 验证通知消息 |
| A | A-7: 端到端完整跑一轮 | 🔴 P0 | 6 步全自动无需外部干预 |
| B | B-1: `!pipeline_activate` 全员切换 | 🔴 P0 | 命令执行后全员频道验证 |
| B | B-2: `!pipeline_activate` min_role=3 | 🔴 P0 | member 执行应被拒绝 |
| B | B-3: `!step_handoff` 下一角色切换 | 🔴 P0 | 执行后下一角色频道验证 |
| B | B-4: `!step_handoff` min_role=3 | 🔴 P0 | member 执行应被拒绝 |
| B | B-5: `persistence.set_agent_channel()` 持久化 | 🟡 P1 | 重连后验证 |
| B | B-6: 返回执行结果 | 🟡 P1 | 验证响应消息 |
| B | B-7: 无活跃管线→错误提示 | 🟡 P1 | 无管线时执行 |
| B | B-8: 工作区不存在→错误提示 | 🟡 P1 | 工作区删除后执行 |

**总数：** 15 项验收（A=7, B=8）

---

## 六、关键约束

1. **⚠️ B 先 A 后** — 方向 B（过渡命令）先开发部署，确保管线有频道切换能力。方向 A（自动切换）在 B 就绪后再开发，复用同一套 `_switch_agent_channel` 函数
2. **⚠️ `_switch_agent_channel` 函数复用 R37 已有代码** — 不重写 MSG_SET_ACTIVE_CHANNEL 发送逻辑，只提取为独立函数
3. **⚠️ 过渡期管线靠 admin-bot 驱动** — 方向 A 上线前，每次 `!step_complete` 后 PM 在工作群 @admin-bot 执行 `!step_handoff`，这是预期的过渡行为
4. **🟢 R50 管线自举验证** — R50 管线本身是方向 B 的实战验证场，完成「用新命令驱动新开发」的自举闭环
5. **🟢 无代码冲突** — 方向 A 和 B 影响 handler.py 中不同函数段（B 是新增命令注册，A 是修改现有 step_complete/rollcall_next），可顺序开发
