# R61 代码审查报告 — F-19/F-20 验证轮次

> **审查者：** 🔍 小周
> **审查对象：** R61 纯验证轮次（零代码修改）
> **审查依据：** `docs/R61/R61-product-requirements.md` + `docs/R61/R61-tech-plan.md`
> **轮次类型：** 纯验证 — 无新增代码，仅确认 `main` 分支已有功能完整性

---

## 0. 审查结论

| 维度 | 评级 |
|:-----|:----:|
| 代码完整性 | ✅ main 分支已完整实现 |
| 技术方案匹配度 | ✅ 方案确认准确 |
| 安全/遗留物 | ✅ 无安全问题 |
| **总体** | **🟢 通过 → Step 5（QA 实测）** |

---

## 1. 审查背景

R61 轮次类型为**纯验证轮次**（零代码开发），目标为在真实管线中验证已在 R53/R60 合入 main 分支的 F-19 和 F-20 功能。因此本审查不涉及代码 diff，而是对技术方案代码完整性结论的复核。

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
| `_cmd_pipeline_start()` | **L1327** | **管线启动后** |
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

## 3. 技术方案发现复核

技术方案 §1.3 指出 `_cmd_create_workspace()` 成员列表（L447-454）使用 `users.get("name")` 而非 `_get_agent_display()`。

**复核确认：** 当前 5 bot 均已通过 R60 配置了 `auth.users["name"]`（小爱、爱泰、小开、小周、泰虾），因此实际显示均为 bot 名，不影响 F-19 核 心验证目标。此差异为低优先级，不影响本轮验证。

---

## 4. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| 敏感信息硬编码 | ✅ 无新增问题 |
| 调试日志残留 | ✅ 无新增问题 |
| TODO/FIXME 残留 | ✅ 零发现 |
| 新增安全风险 | ✅ 无（零代码修改） |

---

## 5. 实施条件检查

| 前置条件 | 状态 | 说明 |
|:---------|:----:|:-----|
| `_get_agent_display()` 在 main 分支 | ✅ | R60 合入 |
| `_broadcast_active_channel()` 在 main 分支 | ✅ | R53 合入 |
| `PIPELINE_ROLE_OVERRIDES` 在 main 分支 | ✅ | R59 合入 |
| R60 bot_name 配置完成 | ✅ | 全员 Gateway 配置正确 |
| main 容器版本 ≥ R60 | ✅ | 验收结论依赖 Step 5 确认 |

---

## 6. 验证建议

由于 R61 为纯验证轮次，审查者**无需验证代码 diff**。核心验证移至 Step 5（泰虾 QA）：

**F-19 验证命令（工作室频道）：**
1. 观察 `!pipeline_start` 后的系统消息成员列表使用 bot 名
2. 观察点名消息使用角色名（arch/dev/review/qa）

**F-20 验证命令（工作室频道）：**
1. `!agent_status` 检查各成员活跃频道 = 新工作室 ID
2. 确认点名通知全员可达（无需手动 `!focus`）

---

## 7. 总结

| 维度 | 评分 | 说明 |
|:-----|:----:|:-----|
| F-19 代码完整性 | ✅ 通过 | `_get_agent_display()` L879 四级回退正确，5 处调用点确认 |
| F-20 代码完整性 | ✅ 通过 | `_broadcast_active_channel()` L3349 完整，`_cmd_pipeline_start()` L1327 同步调用 |
| R59 改动 | ✅ 已合入 | `PIPELINE_ROLE_OVERRIDES` 在 3 处生效 |
| **审查结论** | **🟢 通过** | **main 分支代码完整，可直接进入 Step 5 QA 实测** |

---

**审查完成时间：** 2026-06-30
**送达：** 🦐泰虾（Step 5 测试） + 🦸小爱（管线推进）
