# R61 技术方案 — F-19/F-20 代码完整性确认

> **作者：** 小开（Arch）
> **日期：** 2026-06-30
> **分支：** main
> **目标：** 验证 F-19（角色名替代 agent ID）+ F-20（pipeline_start 自动切活跃频道）代码完整性

---

## 一、代码完整性检查

### 1.1 F-19：`_get_agent_display()` — 角色名显示 ✅

**位置：** `server/handler.py` L879

**代码状态：**
```python
def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
    cards = _load_agent_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]
```

**落点分析：** `_get_agent_display()` 在以下位置被调用：

| 位置 | 行号 | 用途 |
|:----|:----:|:-----|
| 代理注册通知 | L205 | 新代理连接时显示名 |
| 代理注册请求 | L210 | 审批通知显示名 |
| 定向通知 | L1818, L1835 | 发送 @通知时显示名 |
| 成员变更通知 | L3413 | `_notify_member_changed()` |

**结论：** ✅ 代码完整，`display_name > name > role > id[:12]` 四级回退链路实现正确。

---

### 1.2 F-20：`_broadcast_active_channel()` — 自动切频道 ✅

**位置：** `server/handler.py` L3349

**代码状态：**
```python
async def _broadcast_active_channel(ws_id: str) -> dict:
```

**核心流程：**
1. 生成唯一 `ack_task_id` 用于去重
2. 构建 `MSG_SET_ACTIVE_CHANNEL` 消息包
3. 遍历 `ws_obj.members`，对每成员：
   - 持久化通道设置 (`persistence.set_agent_channel`)
   - 对在线连接发送切换消息
4. 注册 ACK 状态 + 30s 超时清理

**调用链：**

| 调用处 | 行号 | 时机 |
|:-------|:----:|:-----|
| `_cmd_create_workspace()` | L457 | 创建工作区的异步任务 |
| `_cmd_pipeline_start()` | L1312 | 管线启动后激活通道（await 同步等待） |
| `_cmd_switch_workspace()` | L1422 | 手动切换工作区 |
| `_cmd_assign_member()` | L822 | 分配成员到步骤 |
| 其他 | L788/L797 | 通道切换相关 |

**结论：** ✅ F-20 完整实现。`_cmd_pipeline_start()` 在 L1312 行同步 `await _broadcast_active_channel(ws_id)` 调用。

---

### 1.3 `_cmd_create_workspace()` 成员列表显示

**位置：** `server/handler.py` L448-455

```python
member_names = []
for mid in member_ids:
    name = users.get(mid, {}).get("name", "")
    if not name:
        role = users.get(mid, {}).get("role", "")
        name = role if role else mid[:12]
    member_names.append(name)
member_list = ", ".join(member_names) if member_names else "无"
```

**对比 `_get_agent_display()` 回退链：**

| 场景 | `_get_agent_display()` | `_cmd_create_workspace()` |
|:----|:----------------------|:--------------------------|
| 1st | `card.display_name` | `auth.users.name` |
| 2nd | `auth.users.name` | `auth.users.role` |
| 3rd | `auth.users.role` | `agent_id[:12]` |
| 4th | `agent_id[:12]` | — |

**评估：** 对于当前 5 bot 均有 `auth.users.name` 配置的场景，成员显示均为 bot 名（小爱、爱泰等），不影响验证。但在 agent_card 有专门 `display_name` 的场景下，工作区创建消息不显示 `display_name`。

**影响：** 低。不影响 F-19 验证核心目标（管线消息、点名通知使用角色名）。

---

## 二、R59 功能确认

`_cmd_pipeline_start()` 中已包含 R59 合入的 `PIPELINE_ROLE_OVERRIDES` 逻辑（L1318）：

```python
_role_overrides = getattr(config, "PIPELINE_ROLE_OVERRIDES", {})
if start_step in _role_overrides:
    target_role = _role_overrides[start_step]
```

**状态：** ✅ R59 关键改动已存在于 main 分支。

---

## 三、潜在风险

| 风险项 | 描述 | 影响评估 |
|:-------|:-----|:---------|
| 部署版本滞后 | GitHub main 与容器版本可能存在代码偏移 | 中 — 需在 Step 3 验证部署版本包含 `_get_agent_display()` |
| 双广播 | `_cmd_create_workspace()` 异步 `create_task` + `_cmd_pipeline_start()` 同步 `await`，两次调用 `_broadcast_active_channel` | 低 — 幂等操作，重复发送无副作用 |

---

## 四、验证建议（供 Step 3 Dev 参考）

1. **在 dev 环境**执行 `!pipeline_start R61-test`，观察：
   - [ ] 工作室创建消息中成员列表使用 bot 名
   - [ ] 点名消息使用角色名
   - [ ] `!agent_status` 显示所有成员活跃频道 = 新工作室 ID
2. **如测试不通过**，优先检查部署容器版本是否与 main 同步
3. 全程无需 `!focus` 命令，验证 F-20 自动切换

---

## 五、结论

| 检查项 | 状态 |
|:-------|:----:|
| F-19：`_get_agent_display()` 代码完整 | ✅ |
| F-20：`_broadcast_active_channel()` 在 `_cmd_pipeline_start()` 中被调用 | ✅ |
| F-20：通道持久化 + ACK 超时完整 | ✅ |
| R59 `PIPELINE_ROLE_OVERRIDES` 合入 | ✅ |
| `_cmd_create_workspace()` 成员列表显示名称 | ✅（使用 `name > role > id`） |
| **整体：代码完整性通过** | ✅ |

**建议：** 直接进入 Step 3（Dev 验证执行），由爱泰在 dev 环境实测即可。无需代码修改。
