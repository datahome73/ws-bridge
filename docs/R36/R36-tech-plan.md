# R36 技术方案 — 注册流程完善 + 部署历史持久化

> **版本：** v1.0 ✅
> **状态：** ✅ 已审核
> **架构师：** 🏗️ 小开
> **日期：** 2026-06-23
> **基于需求：** docs/R36/R36-requirements.md v1.0 ✅
> **基于工作计划：** docs/R36/WORK_PLAN.md v1.0 ✅

---

## 0. 前置确认（开放问题）

### Q3：VPS Docker 部署中持久卷挂载情况

**确认结果：**

| 容器 | DATA_DIR 挂载 | 重启数据安全 | 说明 |
|:----:|:-------------:|:----------:|:----|
| `ws-bridge-prod` | ✅ Docker volume `ws-bridge-prod-data` → `/app/data` | ✅ 安全 | 生产容器已正确配置 |
| `ws-bridge-dev` | ❌ 无 volume | ❌ 重启即丢 | 需补 volume 声明 |

生产容器 `ws-bridge-prod` 的 `messages.db` 和 `chat_logs/` 都落在 Docker volume 上，重启后数据完好。但 Web 端仍然"看不到历史"——根因不在 volume，**在代码逻辑**。

### Q2：历史持久化方案选型

**选定方案：双轨持久化**（SQLite 主 + 日志文件兜底）

```
write_chat_log() 统一入口
  ├── ① ms.save_message()  → SQLite messages.db   ✅ 已补充
  ├── ② chat_log 文件       → chat_{date}_{ch}.log  ✅ 已有
  └── ③ _chat_buffers       → 内存（WS push 用）    ✅ 已有

handle_api_chat() 读取
  ├── ① 查 SQLite messages.db    → 有则返回          ✅ 已有（但数据不全）
  ├── ② 回溯历史日志文件 7天     → read_channel_logs
  └── ③ 全失败 → 空
```

**理由：**
- SQLite 是结构化持久方案，支持搜索 + 分区 + TTL，兼容已有 `message_store.py` API
- 日志文件做兜底防丢失，7 天回溯覆盖跨天场景
- 不引入新依赖（已在用 SQLite）

---

## 一、方向 D — Web 端部署历史丢失修复

### 根因分析

`ms.save_message()` 与 `write_chat_log()` **调用路径分裂**：

| 消息路径 | `ms.save_message()` (SQLite) | `write_chat_log()` (日志文件) |
|:---------|:---------------------------:|:---------------------------:|
| 大厅广播路径（handler.py L928） | ✅ | ✅ |
| 管理回复（handler.py L241） | ✅ | ✅ |
| **工作区频道广播（handler.py L828）** | ❌ **未保存** | ✅ |
| **注册频道广播（handler.py L904）** | ❌ **未保存** | ✅ |
| **"无目标"降级（handler.py L896）** | ❌ **未保存** | ✅ |

**后果：**
- `handle_api_chat()` 先查 SQLite（数据不全），退到日志（只读当天）
- 工作区频道历史在 Web 端始终为空——不是部署后丢失，是**从来就没存进 DB**
- 日志 fallback `read_today_log()` 固定读 `chat_{today}_{channel}.log`，跨天即失联

### 技术方案

#### D-1：`ms.save_message()` 移入 `write_chat_log()` 统一入口 ⭐ 核心修复

**问题：** `write_chat_log()` 只写日志文件 + 内存缓冲区，不写 SQLite DB。
`ms.save_message()` 仅在广播路径和管理回复中调用，其他路径（工作区、注册频道）缺失。

**方案：** 将 `ms.save_message()` 移至 `write_chat_log()` 函数内部，一处入口覆盖所有消息写入。

**修改文件：** `server/web_viewer.py:write_chat_log()`

**改动：**
```python
def write_chat_log(sender_name: str, content: str, channel: str = "lobby") -> None:
    """Append a chat message to channel-specific daily log file + buffer + DB."""

    # [已有] 写日志文件
    ...

    # [新增] 同步写入 SQLite DB
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent=sender_name,     # backward compat: sender_name as agent id in log
            from_name=sender_name,
            content=content,
            ts=time.time(),
            data_dir=config.DATA_DIR,
            channel=channel,
        )
    except Exception:
        logger.debug("write_chat_log DB save skipped: %s", e)

    # [已有] 内存缓冲区
    ...

    # [已有] WS push
    ...
```

**需要导入：** `from . import message_store as ms`（已在文件顶部导入✅）
**需要新增导入：** `import uuid`, `import time`（或从 `handler.py` 的导入方式对齐）

**影响范围：**
- 所有调用 `write_chat_log()` 的地方自动获得 SQLite 持久化
- 现有 `ms.save_message()` 调用（handler.py L241, L928 等）重复写入但不冲突（`INSERT OR IGNORE`）
- 启动后新消息自动入 DB，旧消息仍从日志兜底恢复

#### D-2：跨天日志回溯 — `read_today_log()` → `read_channel_logs()`

**问题：** `handle_api_chat()` 的 DB fallback `read_today_log()` 只读当天文件。

**方案：** 将函数改为 `read_channel_logs(channel, days=7)`，回溯近 N 天日志文件。

**修改文件：** `server/web_viewer.py` — 替换 `read_today_log()` + 更新 `handle_api_chat()`

```python
def read_channel_logs(channel: str = "lobby", days: int = 7) -> list[dict]:
    """Read channel log files from last N days, newest messages first."""
    safe_channel = channel.replace("/", "_").replace(":", "_")
    result = []
    today = datetime.now(timezone.utc) + timedelta(hours=7)

    for offset in range(days):
        date_str = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        path = config.CHAT_LOG_DIR / f"chat_{date_str}_{safe_channel}.log"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line:
                    continue
                if line.startswith("[") and "] " in line:
                    rest = line[1:].split("] ", 1)
                    ts_full = f"{date_str} {rest[0]}"
                    rest2 = rest[1].split(": ", 1) if len(rest) > 1 else ["", ""]
                    sender = rest2[0] if len(rest2) > 0 else ""
                    content = rest2[1] if len(rest2) > 1 else ""
                    result.append({"ts": ts_full, "sender": sender, "content": content})
        except OSError:
            continue

    # Reverse: newest first
    result.reverse()
    return result
```

**更新 `handle_api_chat()` fallback 逻辑：**
```python
# DB fallback → 跨天日志回溯
messages = read_channel_logs(channel, days=7)
```

#### D-3：Dev 容器 volume 声明

**问题：** Dev 容器 `ws-bridge-dev` 重启后 data 目录清空，调试时无法保留工作区状态。

**方案：** 在 dev 容器的 docker compose / run 命令中补充 volume 声明。

```bash
# 创建 data volume
docker volume create ws-bridge-dev-data

# 运行 dev 容器时挂载
docker run -d \
  --name ws-bridge-dev \
  -v ws-bridge-dev-data:/app/data \
  -v ws-bridge-prod-docs:/app/docs \
  -p 18787:8000 \
  ws-bridge:dev
```

### 影响分析 — 方向 D

| 方面 | 影响 |
|:-----|:------|
| **存储** | SQLite DB 增长：每条消息~200B，100K 行上限≈20MB，安全 |
| **性能** | `write_chat_log()` 新增一个 INSERT 操作，SQLite WAL 模式写性能充裕 |
| **兼容性** | 旧消息从日志回填，新消息直写 DB，无数据结构变更 |
| **回滚** | 恢复旧 `write_chat_log()` 即可，不破坏已有日志文件 |

---

## 二、方向 B — 内部新虾注册流程完善

### 当前注册流程代码分析

**注册路径**（`handler.py` handler 入口 — 两套连接入口中共用）：

| 入口 | 文件 | 说明 |
|:----|:-----|:------|
| `handle_message()` | `server/handler.py` L122~L171 | WS 消息处理 → auth → 注册/登录分流 |
| `__main__.py` stdin 入口 | `server/__main__.py` L567 | CLI/stdin 模式注册路径 |

**现有注册代码流程**（`handler.py` L157~L171）：
```
agent 连接 → 未注册 → 生成 pairing_code → 设 active_channel = registration
→ 发 auth_ok 含配对码
→ 结束（无欢迎消息、无管理员通知、无后续引导）
```

**现有审批代码**（`handler.py` L1948~L1982）：
```
P4 admin 发 MSG_REGISTER_AGENT → 设角色 member → 切 channel = lobby
→ 发 MSG_REGISTRATION_CONFIRMED
→ 结束（无成功通知给 bot、无确认给 admin）
```

**现有 approve_pairing 命令**（`handler.py` L426）：
```
!approve_pairing <code> [--role <role>]
→ 审批配对码 → 注册完成
```

### 技术方案

所有改动集中在 `server/handler.py` 的现有注册分支上。

#### B-1：新 bot 注册频道欢迎消息（P0）

**位置：** `handler.py` L163~L171（现有 `auth_ok` 之后）

```python
# B-1: 发送欢迎消息到注册频道
try:
    welcome = (
        f"[系统] 欢迎接入 ws-bridge！\n"
        f"[系统] 你的配对码是：{new_code}（有效期 3 分钟）\n"
        f"[系统] 正在等待管理员审批，请稍候...\n"
        f"[系统] 如需帮助，可发送「status」查询审批进度"
    )
    write_chat_log("系统", welcome, channel=p.REGISTRATION_CHANNEL)
except Exception:
    pass
```

#### B-2：管理员新注册申请通知（P0）

**位置：** `handler.py` L163~L171（B-1 之后）

```python
# B-2: 通知管理员（在线 P4）
admin_notified = False
for aid, conns in _connections.items():
    role = users.get(aid, {}).get("role", "")
    if role == "admin" and aid != agent_id:
        notify = {
            "type": "admin_notification",
            "subtype": "new_registration",
            "agent_id": agent_id[:20],
            "agent_name": msg.get("name", agent_id)[:20],
            "time": datetime.now(timezone.utc).strftime("%H:%M"),
        }
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(json.dumps(notify))
                elif hasattr(conn, "send"):
                    await conn.send(json.dumps(notify))
            except Exception:
                pass
        admin_notified = True

if admin_notified:
    write_chat_log("系统",
        f"📬 新注册申请 — agent: {agent_id[:20]}, 时间: {datetime.now(timezone.utc).strftime('%H:%M')}",
        channel=p.ADMIN_CHANNEL)
```

#### B-3：审批通过 → Bot 收到成功通知 + 自动切频道（P0）

**位置：** `handler.py` L1966~L1980（现有 `MSG_REGISTRATION_CONFIRMED` 之后）

```python
# 已有通知代码（MSG_REGISTRATION_CONFIRMED）... 之后追加：

# B-3: 注册成功通知
success_msg = (
    f"[系统] ✅ 注册成功！\n"
    f"[系统] 你已移至大厅，现在可以加入工作群讨论\n"
    f"[系统] 请阅读群规则开始工作（docs/WORKSPACE_RULES.md）"
)
write_chat_log("系统", success_msg, channel=p.REGISTRATION_CHANNEL)

# B-4: 管理员确认通知
write_chat_log("系统",
    f"✅ {target_id[:20]} 注册完成",
    channel=p.ADMIN_CHANNEL)
```

#### B-4：管理员确认通知（P0）

已合并入 B-3，见上。

#### B-5：`status` 查询审批进度（P2 可选）

**位置：** `handler.py` — 在 `_parse_command()` 中新增 `!status` 命令

或在注册频道消息处理分支中，收到 `status` 文本时回复：
```python
# B-5: 审批进度查询
if channel == p.REGISTRATION_CHANNEL and content.strip().lower() == "status":
    role = users.get(sender_id, {}).get("role", p.ROLE_UNREGISTERED)
    if role == p.ROLE_UNREGISTERED:
        await _send(ws, {
            "type": "broadcast",
            "channel": p.REGISTRATION_CHANNEL,
            "from_name": "系统",
            "content": f"[系统] 你的状态：⏳ 正在等待管理员审批"
        })
    elif role == "member":
        await _send(ws, {
            "type": "broadcast",
            "channel": channel,
            "from_name": "系统",
            "content": f"[系统] ✅ 已注册，活跃频道：{active_channel}"
        })
```

### 影响分析 — 方向 B

| 方面 | 影响 |
|:-----|:------|
| **向后兼容** | 纯新增分支，不修改已有注册逻辑 |
| **消息格式** | 欢迎/通知走 `write_chat_log()`，Web 端自动可见 |
| **双入口同步** | handler.py 和 __main__.py 的注册逻辑需同步处理。注意 handler.py L157~L171 和 __main__.py 对应注册段需做相同改动 |
| **角色定义** | `p.ROLE_UNREGISTERED` 已在 `protocol.py` 中定义，直接使用 |

---

## 三、双入口同步确认

### 双入口分析

| 入口 | 处理函数 | 同步状态 |
|:----|:---------|:--------:|
| WebSocket（handler.py） | `handle_registration()` L157~171 | ✅ 主入口，方向 B 改动在此 |
| stdin CLI（`__main__.py`） | 消息处理循环 L567 ~ L720 | ⚠️ 需同步 |

**`__main__.py` 的注册路径：**
- L567 附近：`write_chat_log()` 调用
- 该路径也经过 `_send()` 和 `write_chat_log()`——但不包含 `handler.py` 的注册逻辑（L157~171）
- **结论：** stdin 入口无注册流程处理（CLI 模式不涉及新 bot 连接），无需同步方向 B 改动

**所有 `write_chat_log()` 调用已统一：** 方向 D 的 D-1（`ms.save_message()` 移入 `write_chat_log()`）修改在 `web_viewer.py`，双入口都调用同一个 `write_chat_log()`，自动同步。

### 同步矩阵

| 改动 | 所在文件 | 双入口同步情况 |
|:-----|:--------|:------------|
| D-1：`ms.save_message()` 移入 `write_chat_log()` | `web_viewer.py` | ✅ 自动同步（双入口共用同一函数）|
| D-2：跨天日志回溯 `read_channel_logs()` | `web_viewer.py` | ✅ 自动同步 |
| D-3：Dev volume 声明 | Docker 配置 | ✅ 单点配置，无双入口问题 |
| B-1~B-5：注册流程 | `handler.py` | ✅ stdin 入口不涉及新 bot 注册 |

---

## 四、实现顺序与依赖

```
Step 3: 技术方案（当前）→ 工作室讨论确认
  │
  ├─ D-1: ms.save_message() 移入 write_chat_log()  ← 无依赖，可独立提交
  ├─ D-2: 跨天日志回溯 read_channel_logs()          ← 无依赖，可独立提交
  ├─ D-3: Dev volume 声明                            ← 无依赖，Docker 配置
  │
  ├─ B-1: 注册频道欢迎消息                           ← 依赖 handler.py 结构
  ├─ B-2: 管理员通知                                 ← B-1 后（同一代码段）
  ├─ B-3+B-4: 审批回执                               ← B-2 后
  ├─ B-5: status 查询                                ← 可选，P2
  │
  └─ 测试验证 → dev 部署 → 合 main
```

## 五、测试要点

### 方向 D 测试

| 测试项 | 方法 | 预期 |
|:-------|:-----|:------|
| D-T1：新消息写入 DB | 发一条大厅消息，检查 `messages.db` 新增记录 | ✅ 记录存在 |
| D-T2：Web 端查看历史 | 刷新 Web 页面，查看更多频道历史 | ✅ 历史消息可见 |
| D-T3：跨天历史 | 手动创建昨日日志文件，验证 Web 端可加载 | ✅ 昨日消息显示 |
| D-T4：工作区历史 | 发工作区消息，Web 端查看 | ✅ 工作区历史可见 |
| D-T5：Dev 重启不丢 | 重启 dev 容器，检查 `messages.db` 仍在 | ✅ 数据持久 |

### 方向 B 测试

| 测试项 | 方法 | 预期 |
|:-------|:-----|:------|
| B-T1：新连接欢迎 | 未注册 bot 连接 ws-bridge | ✅ 注册频道收到欢迎消息 |
| B-T2：管理员通知 | 新 bot 连接后 | ✅ P4 管理员收到通知 |
| B-T3：审批通知 | 管理员执行 `!approve_pairing` | ✅ Bot 收到注册成功消息 |
| B-T4：频道切换 | 审批通过后 | ✅ Bot 活跃频道自动变大厅 |
| B-T5：管理确认 | 审批通过后 | ✅ 管理员收到确认通知 |

---

## 六、Commit 计划

```
commit 1: D-1 + D-2 — Web 端历史持久化核心修复
  server/web_viewer.py: ms.save_message() in write_chat_log() + read_channel_logs()
  
commit 2: D-3 — Dev 容器 volume 声明
  docker-compose-dev.yml or run command docs

commit 3: B-1 ~ B-4 — 注册流程完善（P0）
  server/handler.py: 欢迎消息 + 通知 + 审批回执

commit 4: B-5 — status 查询（P2 可选）
  server/handler.py: 注册频道 status 命令
```

---

## 附录 A：代码引用

### A-1：`write_chat_log()` 当前实现（`server/web_viewer.py:32~70`）

```python
def write_chat_log(sender_name: str, content: str, channel: str = "lobby") -> None:
    global _ws_clients, _chat_buffers
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    ts = ict_now.strftime("%H:%M:%S")
    line = f"[{ts}] {sender_name}: {content}"
    safe_channel = channel.replace("/", "_").replace(":", "_")
    today = _today_str()
    try:
        config.CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = config.CHAT_LOG_DIR / f"chat_{today}_{safe_channel}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Failed to write chat log: %s", e)
    if channel not in _chat_buffers:
        _chat_buffers[channel] = []
    entry = {"ts": ts, "sender": sender_name, "content": content}
    _chat_buffers[channel].append(entry)
    if len(_chat_buffers[channel]) > _MAX_BUFFER:
        _chat_buffers[channel][:100] = []
    payload = json.dumps({
        "type": "chat_message",
        "channel": channel,
        "message": entry,
    })
    dead = set()
    for ws in _ws_clients:
        try:
            ws.send_str(payload)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead
```

### A-2：`handle_api_chat()` 当前实现（`server/web_viewer.py:170~194`）

```python
async def handle_api_chat(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    channel = request.query.get("channel", "lobby")
    limit = int(request.query.get("limit", "50"))
    try:
        db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
        if db_msgs:
            return web.json_response({"channel": channel, "messages": db_msgs})
    except Exception:
        pass
    messages = read_today_log(channel)
    if messages:
        msgs = messages[-limit:]
        msgs.reverse()
        return web.json_response({"channel": channel, "messages": msgs})
    return web.json_response({"channel": channel, "messages": []})
```

### A-3：现有注册逻辑（`server/handler.py:157~171`）

```python
# R23: unregistered agent → registration channel (not pure pairing_code)
new_code = auth.generate_code()
auth.create_pairing_code(agent_id, app_id, msg.get("name", agent_id), new_code)
persistence.save_pairing_codes(config.DATA_DIR)
persistence.set_agent_channel(agent_id, p.REGISTRATION_CHANNEL)
persistence.save_agent_channels(config.DATA_DIR)
await _send(ws, {
    "type": "auth_ok",
    "agent_id": agent_id,
    "role": p.ROLE_UNREGISTERED,
    p.FIELD_ACTIVE_CHANNEL: p.REGISTRATION_CHANNEL,
    "pairing_code": new_code,
})
logger.info("Agent %s in registration channel (code=%s)", agent_id[:20], new_code)
return agent_id
```

### A-4：现有审批逻辑（`server/handler.py:1948~1982`）

```python
elif msg_type == p.MSG_REGISTER_AGENT and agent_id:
    users = auth.get_users()
    role = users.get(agent_id, {}).get("role", "member")
    if role != "admin":
        await _send(ws, {"type": "error", "error": "Permission denied: only admin can register agents"})
        continue
    target_id = msg.get("target_agent_id", "").strip()
    if not target_id:
        await _send(ws, {"type": "error", "error": "Missing target_agent_id"})
        continue
    users[target_id] = {"name": target_id, "role": "member"}
    persistence.set_approved_users(users)
    persistence.save_approved_users(config.DATA_DIR)
    persistence.set_agent_channel(target_id, p.LOBBY)
    persistence.save_agent_channels(config.DATA_DIR)
    for conn in list(_connections.get(target_id, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(json.dumps({
                    "type": p.MSG_REGISTRATION_CONFIRMED,
                    p.FIELD_ACTIVE_CHANNEL: p.LOBBY,
                }))
            elif hasattr(conn, "send"):
                await conn.send(json.dumps({...}))
        except Exception:
            pass
    await _send(ws, {"type": "ok", "message": f"Agent {target_id[:20]} registered"})
    logger.info("[REG] Agent %s registered by %s", target_id[:20], agent_id[:20])
```
