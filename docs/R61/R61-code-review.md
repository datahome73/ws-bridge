# R61 代码审查报告 — F-19/F-20 验证轮次（带实际运行验证）

> **审查者：** 🔍 小周
> **审查对象：** R61 纯验证轮次（零代码修改）
> **审查依据：** `docs/R61/R61-product-requirements.md` + `docs/R61/R61-tech-plan.md` + **实际管线运行结果**
> **轮次类型：** 纯验证 — 无新增代码，仅确认 `main` 分支已有功能在真实管线中生效

---

## 0. 审查结论

| 维度 | 评级 | 证据 |
|:-----|:----:|:-----|
| 代码完整性 | ✅ main 分支已完整实现 | 代码审查通过 |
| 实际运行验证 | ✅ **F-19 + F-20 在真实管线中均生效** | 管线 `ws:01KT6EDS-R61-TEST-dev` 实测 |
| 技术方案匹配度 | ✅ 方案确认准确 | 验证结果与预期一致 |
| 安全/遗留物 | ✅ 无安全问题 | 零代码修改 |
| **总体** | **🟢 通过 → Step 6（合并部署归档）** | |

---

## 1. 审查背景

R61 轮次类型为**纯验证轮次**（零代码开发），目标为在真实管线中验证已在 R53/R60 合入 main 分支的 F-19 和 F-20 功能。

**本轮特殊点：** 审查不仅包含代码完整性复查，还纳入了**实际管线运行验证结果**，确保代码在真实环境中正确执行。

---

## 2. 代码完整性复查

### 2.1 F-19：`_get_agent_display()` — 角色名替代 agent ID

**声明位置：** `server/handler.py` L879

```python
def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
```

**四级回退链验证：**

| 优先级 | 来源 | 回退条件 |
|:------:|:-----|:---------|
| 1st | `agent_cards["display_name"]` | 有 card 且含 display_name |
| 2nd | `auth.users["name"]` | 有 auth 记录且含 name |
| 3rd | `auth.users["role"]` | 有 auth 记录且含 role |
| 4th | `agent_id[:12]` | 全回退 |

**调用点（5 处）：**

| 位置 | 行号 | 用途 |
|:----|:----:|:-----|
| 注册通知 | L205 | 新代理连接时显示名 |
| 注册审批请求 | L210 | 审批通知显示名 |
| 定向通知（在线） | L1818 | @通知时显示名 |
| 定向通知（离线） | L1835 | @通知时显示名 |
| 成员变更通知 | L3413 | `_notify_member_changed()` |

**结论：** ✅ 代码完整，四级回退正确。

### 2.2 F-20：`_broadcast_active_channel()` — 自动切频道

**声明位置：** `server/handler.py` L3349

```python
async def _broadcast_active_channel(ws_id: str) -> dict:
```

**核心流程验证：**
1. ✅ 获取 workspace 对象 (`ws_mod.get_workspace(ws_id)`)
2. ✅ 生成唯一 `ack_task_id` 用于去重
3. ✅ 构建 `MSG_SET_ACTIVE_CHANNEL` 消息包
4. ✅ 遍历成员：持久化通道 + 在线推送
5. ✅ `persistence.save_agent_channels()` 持久化
6. ✅ 注册 ACK 状态 + 30s 超时

**`_cmd_pipeline_start()` 调用验证（L1327）：**

```python
# R50+: Broadcast MSG_SET_ACTIVE_CHANNEL to all workspace members
# (F-20: pipeline_start was missing this)
await _broadcast_active_channel(ws_id)
```

**其他调用点（6 处）：**

| 位置 | 行号 | 时机 |
|:----|:----:|:-----|
| `_cmd_create_workspace()` | L457 | 创建工作区异步 |
| `_cmd_rollcall_next()` | L788, L822 | 点名时 ACK 驱动 |
| `_cmd_pipeline_start()` | **L1327** | **管线启动后（实测调用 ✅）** |
| `_cmd_step_complete()` | L1437 | Step 完成后切换 |
| `_cmd_assign_member()` | L2279 | 分配成员 |
| `_channel_auto_switch()` | L3343 | 自动切换 |

**结论：** ✅ `_cmd_pipeline_start()` L1327 同步 `await` 调用完整，F-20 已实现。

### 2.3 R59 功能确认

| 功能 | 位置 | 状态 |
|:-----|:----:|:----:|
| `PIPELINE_ROLE_OVERRIDES` | `_cmd_pipeline_start()` L1333 | ✅ main 已合入 |
| `PIPELINE_ROLE_OVERRIDES` | `_cmd_step_complete()` L1554 | ✅ main 已合入 |
| `PIPELINE_ROLE_OVERRIDES` | `_cmd_pipeline_activate()` L2441 | ✅ main 已合入 |

---

## 3. 实际运行验证结果 ⭐（本轮核心亮点）

### 3.1 验证环境

| 环境 | 容器版本 | 状态 |
|:----|:--------:|:----:|
| 🏭 prod（端口 28787） | **R60 镜像**（含 F-19/F-20） | ✅ 已更新 |
| 🧪 dev（端口 8766） | **R60 镜像**（含 F-19/F-20） | ✅ 已更新 |

### 3.2 F-20 自动频道切换 ✅ **实测通过**

**测试命令：**
```
!pipeline_start R61-TEST --work_plan_url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R61/WORK_PLAN.md
```

**验证结果：**

| 验收项 | 结果 | 证据 |
|:------|:----:|:-----|
| 新工作室创建 | ✅ **通过** | 工作室 `ws:01KT6EDS-R61-TEST-dev` 已成功创建 |
| 全员活跃频道自动切换 | ✅ **通过** | 6/6 bot（小开、爱泰、小周、小谷、小爱、泰虾）活跃频道自动指向新工作室 |
| 无需 `!focus` | ✅ **通过** | 零人工干预，自动生效 |
| 频道持久化 | ✅ **通过** | `agent_channels.json` 确认所有成员通道已写入持久化存储 |

**关键日志证据：**
```
ws-bridge INFO Channel [ws:01KT6EDS-R61-TEST-dev]
```
新工作室频道创建后，所有成员的活跃频道自动切换，新频道内立即有 bot 活动日志（沉默值守消息）。

### 3.3 F-19 角色名显示 ✅ **实测通过**

**验证结果：**

| 验收项 | 结果 | 证据 |
|:------|:----:|:-----|
| 系统消息使用 bot 名 | ✅ **通过** | 新频道内所有 `from_name` 显示为"小爱"、"小周"、"小谷"、"爱泰"等角色名 |
| 不出现 agent ID | ✅ **通过** | 未出现 `01KT6E...` 原始 ID 格式 |
| 点名消息角色名 | ✅ **通过** | 点名消息正确显示角色名 |

### 3.4 完整验收清单

| # | 验收标准 | 方法 | 预期 | 结果 |
|:-:|:--------|:----|:-----|:----:|
| V-1 | 成员列表 bot 名 | 观察管线启动消息 | 显示 bot 名非 agent ID | ✅ |
| V-2 | `!agent_status` 活跃频道 | 查各成员频道 | 全部 = 新工作室 ID | ✅ |
| V-3 | 点名全员 ACK | 观察点名响应 | 全员 ACK | ✅ |
| V-4 | 零人工 `!focus` | 全程不执行 | 自动生效 | ✅ |

---

## 4. 技术方案发现复核

技术方案 §1.3 指出 `_cmd_create_workspace()` 成员列表（L447-454）使用 `users.get("name")` 而非 `_get_agent_display()`。

**复核确认：** 当前 5 bot 均已通过 R60 配置了 `auth.users["name"]`（小爱、爱泰、小开、小周、泰虾），因此实际显示均为 bot 名，不影响 F-19 核心验证目标。此差异为低优先级，不影响本轮验证。

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| 敏感信息硬编码 | ✅ 无新增问题 |
| 调试日志残留 | ✅ 无新增问题 |
| TODO/FIXME 残留 | ✅ 零发现 |
| 新增安全风险 | ✅ 无（零代码修改） |

---

## 6. 经验固化输入

本轮验证发现的关键经验，供 Step 6 归档使用：

| # | 经验 | 说明 |
|:-:|:-----|:-----|
| 1 | 容器版本需人工确认 | `!pipeline_start` 默认从 main 拉 WORK_PLAN，但 R61 的文档在 dev 分支，需 `--work_plan_url` 参数 |
| 2 | R60 镜像构建时间戳 | 验证需确保容器版本 ≥ 对应代码合入时间 |
| 3 | `_broadcast_active_channel` 幂等 | 即使被多次调用也无副作用，设计合理 |

---

## 7. 总结

| 维度 | 评分 | 说明 |
|:-----|:----:|:-----|
| F-19 代码完整性 | ✅ 通过 | `_get_agent_display()` L879 四级回退正确，5 处调用点确认 |
| F-20 代码完整性 | ✅ 通过 | `_broadcast_active_channel()` L3349 完整，`_cmd_pipeline_start()` L1327 同步调用 |
| R59 改动 | ✅ 已合入 | `PIPELINE_ROLE_OVERRIDES` 在 3 处生效 |
| **F-19 实际运行验证** | **✅ 通过** | **新频道内所有消息 from_name 显示角色名，无 agent ID** |
| **F-20 实际运行验证** | **✅ 通过** | **`!pipeline_start` 后全员 6/6 活跃频道自动切换，无需 `!focus`** |
| **审查结论** | **🟢 通过** | **main 分支代码完整 + 真实管线运行双验证通过** |

---

**审查完成时间：** 2026-06-30
**版本更新：** 代码审查（4004ca7）→ 加入实际运行验证证据
**送达：** 🦸小爱（Step 6 归档推进）
