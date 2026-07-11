# R79 技术方案 — 新虾注册流程完善：欢迎消息 + 审批通知 + 自动切频道 🎯

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-09
> **基于需求：** docs/R79/R79-product-requirements.md v1.0
> **基线：** `1dbdee7`（main — R78 合并部署）
> **改动范围：** `server/handler.py`（~53 行净增）

---

## 目录

1. [handle_agent_card_register() 当前实现分析](#1-handle_agent_card_register-当前实现分析)
2. [方向 A：注册欢迎消息](#2-方向-a注册欢迎消息)
3. [方向 B：管理员审批通知](#3-方向-b管理员审批通知)
4. [方向 C：自动频道切换](#4-方向-c自动频道切换)
5. [方向 D：大厅广播（默认关闭）](#5-方向-d大厅广播默认关闭)
6. [配置常量](#6-配置常量)
7. [改动汇总](#7-改动汇总)
8. [兼容性分析](#8-兼容性分析)

---

## 1. handle_agent_card_register() 当前实现分析

### 1.1 注册流程全景

```
Bot 连 WS → handle_register() → register_ok (包含 agent_id + api_key)
         → Bot 发 agent_card_register → handle_agent_card_register()
         → register_from_agent() → 保存 Agent Card → 返回确认
         → [结束 — 无后续行为]
```

### 1.2 handle_agent_card_register() 当前代码

**位置：** `server/handler.py` L264-266

```python
async def handle_agent_card_register(ws, agent_id: str, msg: dict) -> dict:
    """R72: Bot 自主注册 Agent Card。返回确认消息。"""
    return ac_mod.register_from_agent(agent_id, msg)
```

是一个**透传函数**——所有逻辑委托给 `agent_card.py` 的 `register_from_agent()`。

### 1.3 register_from_agent() 完成的工作

**位置：** `server/agent_card.py` L335-391

| 步骤 | 动作 | 说明 |
|:----:|:------|:------|
| 1 | 提取 display_name / pipeline_roles / trigger_keyword 等 | 从 msg 解析 |
| 2 | 构建 card dict | 含 display_name、pipeline_roles、skills、status 等 |
| 3 | 持久化到 `_cards[agent_id]` + save_cards() | 写入 `agent_cards.json` |
| 4 | 更新 `_ROLE_AGENT_MAP`（走 PipelineContextManager） | R78 已加固 |
| 5 | 返回确认 dict | `{"type": "register_ok", "agent_id": agent_id, ...}` |

### 1.4 调用路径

```
__main__.py ws_handler L107:
  elif msg_type == "agent_card_register" and agent_id:
      result = await handle_agent_card_register(ws, agent_id, data)
      await ws.send_json(result)
```

### 1.5 关键观察

| 观察 | 影响 |
|:-----|:------|
| `ws`（WebSocket 连接）在 handle_agent_card_register 中可用 | 可向 bot 的私有连接发送消息 |
| 注册时 agent_id 已确定 | 欢迎消息可以直接发到 bot 的 WebSocket |
| 注册流程全部在 handler.py 中完成 | 追加行为在同一文件中完成，无需跨模块调用 |
| `register_from_agent()` 是同步函数，handle_agent_card_register 是异步 | 追加行为可以是异步的（ws.send、broadcast 等） |

---

## 2. 方向 A：注册欢迎消息

### 2.1 欢迎消息工具函数

```python
# server/handler.py — 新增工具函数

def _build_registration_welcome(agent_id: str, display_name: str,
                                pipeline_roles: list[str]) -> str:
    """构建注册欢迎消息文本。"""
    roles_str = ", ".join(pipeline_roles) if pipeline_roles else "未声明"
    return (
        f"🎉 欢迎加入 ws-bridge！\n\n"
        f"你已成功注册，Agent ID: {agent_id[:16]}...\n"
        f"当前角色: {roles_str}\n\n"
        f"📋 下一事项：\n"
        f"  1. 配置 config.yaml（bot_name / mention_keyword）\n"
        f"  2. 阅读 WORKSPACE_RULES.md 了解平台规则\n"
        f"  3. 在频道中 @管理员 确认配置完毕\n\n"
        f"💡 帮助：发送 !help 查看可用命令"
    )
```

### 2.2 发送到 bot 私有连接

欢迎消息应发送到 **bot 注册时使用的 WebSocket 连接**（`ws` 参数），而非 inbox 通道。原因：

| 理由 | 说明 |
|:-----|:------|
| 注册时 bot 的 inbox 通道可能还未被 bot 监听 | bot 刚完成注册，ws_client.py 可能尚未开始监听 inbox |
| `ws` 连接是当前活跃连接 | 发到 ws 连接的消息 bot 一定收到 |
| inbox 通道是持久化通道 | bot 重连后可通过离线推送重新收到 |

```python
# 在 handle_agent_card_register() 末尾追加（try/except 包裹）

# R79 A: 发送欢迎消息到注册连接
try:
    welcome_text = _build_registration_welcome(
        agent_id, card.get("display_name", ""),
        card.get("pipeline_roles", []),
    )
    await _send(ws, {
        "type": p.MSG_BROADCAST,
        "channel": persistence.get_agent_channel(agent_id) or p.LOBBY,
        "from_name": "系统",
        "from_agent": SYSTEM_AGENT_ID,
        "content": welcome_text,
        "ts": time.time(),
    })
    logger.info("R79: Welcome message sent to %s (%s)", agent_id[:20], display_name)
except Exception as e:
    logger.warning("R79: Failed to send welcome to %s: %s", agent_id[:20], e)
```

### 2.3 与现有 handle_agent_card_register 的整合

```python
async def handle_agent_card_register(ws, agent_id: str, msg: dict) -> dict:
    """R72: Bot 自主注册 Agent Card。返回确认消息。"""
    result = ac_mod.register_from_agent(agent_id, msg)

    # R79 A: 发送欢迎消息
    # (try/except 包裹，不阻断注册流程)
    card = ac_mod.get_card(agent_id) or {}
    display_name = card.get("display_name", "") or agent_id[:12]
    pipeline_roles = card.get("pipeline_roles", [])
    try:
        welcome_text = _build_registration_welcome(
            agent_id, display_name, pipeline_roles,
        )
        target_channel = persistence.get_agent_channel(agent_id) or p.LOBBY
        await _send(ws, {
            "type": p.MSG_BROADCAST,
            "channel": target_channel,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": welcome_text,
            "ts": time.time(),
        })
        logger.info("R79: Welcome sent to %s (%s)", agent_id[:20], display_name)
    except Exception as e:
        logger.warning("R79: Welcome failed for %s: %s", agent_id[:20], e)

    # R79 B+C: 管理员通知 + 频道切换
    # (见 §3 和 §4)
    ...

    return result
```

**注意：** `register_from_agent()` 返回的 result dict 包含 `agent_id` 和 `display_name`，但 `card` 信息需从 `ac_mod.get_card()` 获取，因为 register_from_agent 保存后 card 才可用。

---

## 3. 方向 B：管理员审批通知

### 3.1 BROADCAST_ADMINS 配置读取

**来源：** `server/config.py` L13-15

```python
BROADCAST_ADMINS: set[str] = set(
    filter(None, os.environ.get("BROADCAST_ADMINS", "").split(","))
)
```

从环境变量 `BROADCAST_ADMINS` 读取，逗号分隔的 display_name 列表。例如：

```bash
export BROADCAST_ADMINS="大宏,小爱"
```

### 3.2 管理员自免判断

当新注册的 bot 的 display_name 在 `BROADCAST_ADMINS` 中时，不发送管理员通知（管理员本人注册无需通知管理员自己）。

```python
def _should_notify_admins(display_name: str) -> bool:
    """判断是否应向管理员发送新 bot 注册通知。
    
    如果注册者本人是管理员（display_name 在 BROADCAST_ADMINS 中），
    则不发通知——管理员知道自己注册了。
    """
    return display_name not in config.BROADCAST_ADMINS
```

### 3.3 通知消息发送

`_admin` 频道是已定义的通道（`protocol.py` 中 `ADMIN_CHANNEL = "_admin"`）。通知通过 `handle_broadcast()` 广播到 `_admin` 频道。

```python
def _build_admin_notification(agent_id: str, display_name: str,
                              pipeline_roles: list[str]) -> str:
    """构建管理员通知消息文本。"""
    roles_str = ", ".join(pipeline_roles) if pipeline_roles else "未声明"
    return (
        f"📢 新 bot 注册通知\n\n"
        f"Agent ID: {agent_id[:16]}...\n"
        f"显示名称: {display_name}\n"
        f"角色: {roles_str}\n\n"
        f"操作:\n"
        f"  !approve {agent_id}   批准加入\n"
        f"  !agent_card set {agent_id} roles:...   修改角色"
    )
```

发送到 `_admin` 频道：

```python
# R79 B: 管理员通知（非管理员注册时）
try:
    if _should_notify_admins(display_name):
        notify_text = _build_admin_notification(
            agent_id, display_name, pipeline_roles,
        )
        # 广播到 _admin 频道
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": p.MSG_BROADCAST,
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": notify_text,
            "ts": time.time(),
        })
        logger.info("R79: Admin notification sent for %s", agent_id[:20])
except Exception as e:
    logger.warning("R79: Admin notification failed for %s: %s", agent_id[:20], e)
```

### 3.4 _broadcast_to_channel 的实现

```python
async def _broadcast_to_channel(channel: str, payload: dict) -> int:
    """向指定频道的所有连接广播消息。返回发送数。"""
    payload_json = json.dumps(payload)
    sent = 0
    for aid, conns in _connections.items():
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload_json)
                elif hasattr(conn, "send"):
                    await conn.send(payload_json)
                sent += 1
            except Exception:
                pass
    # 同时持久化
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent=SYSTEM_AGENT_ID,
            from_name="系统",
            content=payload.get("content", ""),
            ts=time.time(),
            data_dir=config.DATA_DIR,
            channel=channel,
        )
        write_chat_log("系统", payload.get("content", ""), channel=channel)
    except Exception:
        pass
    return sent
```

---

## 4. 方向 C：自动频道切换

### 4.1 MSG_SET_ACTIVE_CHANNEL 发送模板

参考现有 `_broadcast_active_channel()`（L4973-5000）的实现：

```python
switch_payload = json.dumps({
    "type": p.MSG_SET_ACTIVE_CHANNEL,
    p.FIELD_CHANNEL: ws_id,      # 要切换到的频道 ID
    p.FIELD_TASK_ID: ack_task_id,  # ACK 追踪 ID
    "from_name": "系统",
    "from": "系统",
    "content": f"请将活跃频道切换至 {ws_id} 后回复 ACK",
    "ts": time.time(),
})
```

### 4.2 注册后的频道切换

注册完成后，bot 应从注册通道切换到大厅（`lobby`）：

```python
# R79 C: 切活跃频道到大厅
try:
    # 1. 持久化活跃频道（重连时恢复）
    persistence.set_agent_channel(agent_id, p.LOBBY)

    # 2. 向 bot 的注册连接发送 MSG_SET_ACTIVE_CHANNEL
    switch_payload = {
        "type": p.MSG_SET_ACTIVE_CHANNEL,
        p.FIELD_CHANNEL: p.LOBBY,
        "from_name": "系统",
        "from": "系统",
        "content": "注册完成，频道已切换至大厅",
        "ts": time.time(),
    }
    await _send(ws, switch_payload)
    logger.info("R79: Channel switched to lobby for %s", agent_id[:20])
except Exception as e:
    logger.warning("R79: Channel switch failed for %s: %s", agent_id[:20], e)
```

**与 `_broadcast_active_channel()` 的区别：**

| 方面 | 现有 `_broadcast_active_channel()` | R79 频道切换 |
|:-----|:-----------------------------------|:--------------|
| 目标 | 整个 workspace 的所有成员 | 单个 bot |
| 频道 | workspace ID | lobby |
| ACK 等待 | 有（30s timeout） | 无（简单通知） |
| 发送方式 | 遍历所有成员的连接 | 通过 `ws` 参数直接发送 |

### 4.3 现有 _agent_active_channels 持久化

`persistence.set_agent_channel(agent_id, channel)` 将活跃频道写入持久化文件。重连时通过 `auth.py` 处理 `auth` 消息时恢复：

```python
# 在 __main__.py 的 auth 处理中
_agent_active_channels[agent_id] = persistence.get_agent_channel(agent_id) or LOBBY
```

---

## 5. 方向 D：大厅广播（默认关闭）

### 5.1 开关控制

```python
# server/handler.py 顶部常量
# R79 D: 注册后大厅广播开关（默认关闭）
REGISTRATION_BROADCAST_ENABLED: bool = (
    os.environ.get("REGISTRATION_BROADCAST_ENABLED", "0") == "1"
)
```

### 5.2 广播消息

```python
# R79 D: 大厅广播（默认关闭）
if REGISTRATION_BROADCAST_ENABLED:
    try:
        broadcast_text = (
            f"🆕 新伙伴加入: {display_name}\n"
            f"角色: {', '.join(pipeline_roles) if pipeline_roles else '未声明'}"
        )
        await _broadcast_to_channel(p.LOBBY, {
            "type": p.MSG_BROADCAST,
            "channel": p.LOBBY,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": broadcast_text,
            "ts": time.time(),
        })
    except Exception as e:
        logger.warning("R79 D: Lobby broadcast failed: %s", e)
```

---

## 6. 配置常量

### 6.1 SYSTEM_AGENT_ID

```python
# server/handler.py 顶部 — 系统消息发送者标识
SYSTEM_AGENT_ID: str = "_system"
```

### 6.2 REGISTRATION_BROADCAST_ENABLED

```python
REGISTRATION_BROADCAST_ENABLED: bool = (
    os.environ.get("REGISTRATION_BROADCAST_ENABLED", "0") == "1"
)
```

### 6.3 常量声明位置

两者均声明在 `server/handler.py` 顶部模块级常量区（约 L40-50，与 `_PIPELINE_STATE` / `_PIPELINE_CONFIG` 同级）。

### 6.4 完整改造后的 handle_agent_card_register()

```python
async def handle_agent_card_register(ws, agent_id: str, msg: dict) -> dict:
    """R72: Bot 自主注册 Agent Card。返回确认消息。
    
    R79: 追加欢迎消息 + 管理员通知 + 频道切换。
    """
    result = ac_mod.register_from_agent(agent_id, msg)

    # ── R79: 注册后行为（全部 try/except，不阻断注册流程）──
    try:
        card = ac_mod.get_card(agent_id) or {}
        display_name = card.get("display_name", "") or agent_id[:12]
        pipeline_roles = card.get("pipeline_roles", [])

        # A: 发送欢迎消息到 bot 连接
        try:
            welcome = _build_registration_welcome(agent_id, display_name, pipeline_roles)
            target_ch = persistence.get_agent_channel(agent_id) or p.LOBBY
            await _send(ws, {
                "type": p.MSG_BROADCAST, "channel": target_ch,
                "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
                "content": welcome, "ts": time.time(),
            })
            logger.info("R79 A: Welcome sent to %s", agent_id[:20])
        except Exception as e:
            logger.warning("R79 A: Welcome failed for %s: %s", agent_id[:20], e)

        # B: 管理员通知（非管理员注册）
        try:
            if display_name not in config.BROADCAST_ADMINS:
                notify = _build_admin_notification(agent_id, display_name, pipeline_roles)
                await _broadcast_to_channel(p.ADMIN_CHANNEL, {
                    "type": p.MSG_BROADCAST, "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
                    "content": notify, "ts": time.time(),
                })
                logger.info("R79 B: Admin notified for %s", agent_id[:20])
        except Exception as e:
            logger.warning("R79 B: Admin notification failed: %s", e)

        # C: 切活跃频道到大厅
        try:
            persistence.set_agent_channel(agent_id, p.LOBBY)
            await _send(ws, {
                "type": p.MSG_SET_ACTIVE_CHANNEL,
                p.FIELD_CHANNEL: p.LOBBY,
                "from_name": "系统", "from": "系统",
                "content": "注册完成，频道已切换至大厅",
                "ts": time.time(),
            })
            logger.info("R79 C: Switched %s to lobby", agent_id[:20])
        except Exception as e:
            logger.warning("R79 C: Channel switch failed: %s", e)

        # D: 大厅广播（默认关闭）
        if REGISTRATION_BROADCAST_ENABLED:
            try:
                bcast = f"🆕 新伙伴加入：{display_name}\n角色：{', '.join(pipeline_roles) if pipeline_roles else '未声明'}"
                await _broadcast_to_channel(p.LOBBY, {
                    "type": p.MSG_BROADCAST, "channel": p.LOBBY,
                    "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
                    "content": bcast, "ts": time.time(),
                })
            except Exception as e:
                logger.warning("R79 D: Lobby broadcast failed: %s", e)

    except Exception as e:
        logger.warning("R79: Registration post-process error (non-fatal): %s", e)

    return result
```

---

## 7. 改动汇总

### 7.1 文件清单

仅 `server/handler.py`，~53 行净增：

| # | 位置 | 改动 | 行数 | 方向 |
|:-:|:-----|:------|:----:|:----:|
| 1 | 模块顶部常量区 | 新增 `SYSTEM_AGENT_ID` | 1 | — |
| 2 | 模块顶部常量区 | 新增 `REGISTRATION_BROADCAST_ENABLED` | 2 | D |
| 3 | 新增函数 | `_build_registration_welcome()` | ~12 | A |
| 4 | 新增函数 | `_build_admin_notification()` | ~10 | B |
| 5 | 新增函数 | `_broadcast_to_channel()` | ~18 | B/D |
| 6 | 新增函数 | `_should_notify_admins()` | ~4 | B |
| 7 | L264-266 改造 | `handle_agent_card_register()` 末尾追加 | ~25 | A+B+C+D |
| | **合计** | | **~53 行净增** | |

### 7.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `server/agent_card.py` | 注册逻辑不变，仅追加 handler 行为 |
| `server/config.py` | `BROADCAST_ADMINS` 已存在 |
| `shared/protocol.py` | 不新增消息类型 |
| Bot 代码 | 注册流程对 bot 透明 |
| Web/前端 | 不涉及 |

---

## 8. 兼容性分析

### 8.1 现有 bot 注册流程

| 场景 | 当前行为 | 改造后行为 | 兼容性 |
|:-----|:---------|:-----------|:-------|
| 正常 bot 注册 + card 注册 | register_ok → card register_ok | register_ok → card register_ok + 欢迎消息 + 通知 + 切频道 | ✅ 向后兼容（新增行为，bot 原有流程不变） |
| 欢迎消息发送失败 | — | log warning，注册继续 | ✅ try/except 保护 |
| 管理员通知发送失败 | — | log warning，注册继续 | ✅ try/except 保护 |
| 频道切换失败 | — | log warning，bot 下次重连时恢复 | ✅ try/except + 持久化双保险 |
| 管理员自己注册（display_name in BROADCAST_ADMINS） | — | 不发通知 | ✅ 自免判断 |
| 方向 D 默认关闭 | — | 无广播 | ✅ 默认 false |
| 方向 D 开启 | — | 大厅可见新 bot 加入 | ✅ 环境变量控制 |
| 旧 bot 在注册后收到欢迎消息 | — | 可能收到重复欢迎 | ⚠️ 仅首次注册后触发，不影响后续 |
| bot 重连/重新认证 | — | 不触发 welcome（仅 agent_card_register 触发） | ✅ 仅新注册 |

### 8.2 执行顺序

```
A: 欢迎消息 ──→ B: 管理员通知 ──→ C: 频道切换 ──→ [D: 大厅广播]
```

A→B→C→D 顺序执行，非并行。这确保：
1. 欢迎消息先到达 bot（bot 知道自己注册成功了）
2. 管理员收到通知（admin 知道有新 bot）
3. bot 频道切到大堂（bot 可以参与群聊）
4. 大厅广播（可选，默认关闭）

任意步骤失败不影响后续步骤。

### 8.3 重连兼容

如果 MSG_SET_ACTIVE_CHANNEL 因连接断开未送达：

```python
# __main__.py 中 auth 处理 — 自动恢复活跃频道
_agent_active_channels[agent_id] = persistence.get_agent_channel(agent_id) or LOBBY
```

bot 重连时从持久化读取 `_agent_active_channels`，值为 `lobby`（步骤 C 中 `persistence.set_agent_channel(agent_id, p.LOBBY)` 已持久化）。因此频道切换是可靠的。

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| 新代码异常阻断注册 | 低 | 高 | 全部 `try/except`，异常仅 log warning，register_ok 正常返回 |
| `ws` 连接已关闭后仍尝试发送 | 低 | 低 | `_send()` 内部已有 try/except |
| `BROADCAST_ADMINS` 未配置（空集） | 中 | 低 | 空集时所有注册都发管理员通知（保守行为） |
| 欢迎消息中包含过长 agent_id 有安全风险 | 低 | 低 | 使用 `agent_id[:16]` 截断 |
| 注册后立即断连，MSG_SET_ACTIVE_CHANNEL 丢失 | 低 | 低 | 持久化已写 `lobby`，重连时自动恢复 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R79 技术方案：handler.py 追加欢迎消息 + 管理员通知 + 频道切换 + 默认关闭的大厅广播 |
