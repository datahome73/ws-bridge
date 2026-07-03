# R67 产品需求 — Agent Card 系统统一与角色映射持久化 🎯

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-03
> **本轮改动范围：** `server/agent_card.py`、`server/handler.py`（Agent Card 相关区域）
> **参考：** docs/ARCHITECTURE-REQUIREMENTS.md §六 P0、§3.5 Agent Card 注册表、R63 Agent Card 经验

---

## 1. 问题背景

### 1.1 现状：Agent Card 系统有双重存储，格式不同步，角色映射持久化缺失

ws-bridge 现有的 Agent Card 系统有**两个独立的数据存储路径**，互不感知：

| 存储路径 | 读取者 | 写入者 | 当前是否存在 |
|:---------|:-------|:-------|:-----------:|
| `config/agent_cards.json` | `agent_card.py._load_cards()` | 手动编辑 or `agent_card.py._save_cards()` | ✅ 存在 |
| `{DATA_DIR}/data/agent_cards.json` | `handler.py._load_agent_cards()` | `handler.py._save_agent_cards()` | ❌ **不存在** |

而且两者的**数据格式也不同**：

```json
// config/agent_cards.json — 旧 R63 格式
{
  "arch-bot": {
    "agent_id": "arch-bot",
    "display_name": "架构师",
    "role": "architect",             // ← 单字符串，非数组
    "skills": [                      // ← 对象数组 [{id, description}]
      {"id": "write-tech-plan", "description": "编写技术方案"}
    ],
    "triggers": ["!arch", "!方案"],  // ← 旧字段名
    "state": "online"
  }
}

// handler.py 期望的格式 — 新 pipeline_roles 数组格式
{
  "arch-bot": {
    "pipeline_roles": ["arch"],       // ← 数组
    "display_name": "架构师",
    "skills": ["write-tech-plan"],    // ← 字符串数组
    "trigger_preference": {           // ← 不同字段名/结构
      "mode": "mention",
      "mention_keyword": "架构师"
    }
  }
}
```

**两种格式的数据互不兼容，两个存储路径的数据互不感知。** 当 handler.py 写卡时，agent_card.py 不知道；当 agent_card.py 写卡时，handler.py 不知道。`_refresh_role_agent_map()` 从 `_load_agent_cards()` 读取——但该函数读的是不存在的 `data/agent_cards.json`，所以**角色映射实际上总是空的**。

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | **历史遗留** | R49 在 handler.py 中创建了 `_load/save_agent_cards()`，R63 在 `agent_card.py` 中创建了另一套 load/save。两拨开发互不知晓对方，各自用了不同路径和格式 |
| 2 | **无主存储设计** | 没有规定哪个路径是「权威源」，两个系统各自读写自己的文件。`agent_card.py` 的 `register_agent()` 写 `config/agent_cards.json`，但 handler.py 的 `!agent_card set` 命令写 `data/agent_cards.json` |
| 3 | **格式未随 schema 演进** | R63 Phase 3 扩展了 `pipeline_roles` 数组格式，但 `config/agent_cards.json` 仍使用旧的单 `role` 字段 + `triggers`。迁移从未发生 |
| 4 | **缺少文件变动监听** | 手动编辑 `config/agent_cards.json` 后，需要 `!agent_card reload` → `!agent_role_map --refresh` 两步操作才能生效，操作链路长且易忘 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **角色映射实际不可用** | `_refresh_role_agent_map()` 读取不存在的 `data/agent_cards.json`，`_ROLE_AGENT_MAP` 始终为空。虽然管线因 fallback 到 `_get_agents_by_role()` 的 auth fallback 而未崩溃，但角色映射的核心功能等于没工作 |
| 🔴 **容器重建后全丢** | `_ROLE_AGENT_MAP` 是内存 dict，容器重建后必须重新 `!agent_card register` + `!agent_role_map --refresh`。Agent Card 的「持久化」名存实亡 |
| 🟡 **管理体验差** | 修改 Agent 角色需要 `!agent_card set`（写 data/agent_cards.json）和手动改 `config/agent_cards.json` 两处操作才能保持一致 |
| 🟡 **R66 残留** | `_load_step_config()` 在 watchdog/timeout 函数中有 14 处残留，虽非阻塞但会干扰后续开发 |
| 🟢 **改动范围集中** | 主要改 `agent_card.py`（统一存储路径和格式）+ `handler.py`（去掉重复的 `_load/save_agent_cards`，统一调用 `agent_card.py`）。数据迁移是一次性的 JSON 格式转换 |
| 🟢 **不影响管线行为** | Agent Card 系统独立于管线状态机，改动不触及其他功能。无旧格式兼容问题（旧格式数据本身就是孤立的——从未正确加载过） |

---

## 2. 功能需求

### 设计原则

> **agent_card.py 为主存储层：** 所有 Agent Card 的读写统一走 `agent_card.py`（路径：`config/agent_cards.json`）。`handler.py` 去掉重复的 `_load/save_agent_cards()` 函数，改为调用 `agent_card.py` 接口。
>
> **格式统一：** 统一使用新格式（`pipeline_roles` 数组、`skills` 字符串数组、`trigger_preference` dict、`status` 字段）。旧格式数据在迁移时自动转换。
>
> **文件变动即生效：** 修改 `config/agent_cards.json` 后，角色映射自动重建，无需手动 reload。

---

### 方向 A（核心）：Agent Card 存储统一 + 格式对齐 🔴 P0

**核心思路：** 统一两个存储路径为一个，统一格式为新 schema，数据从旧格式迁移。

#### A1 — 统一存储路径

**位置：** `server/agent_card.py`

当前 `agent_card.py` 的路径是 `config/agent_cards.json`。`handler.py` 的路径是 `{DATA_DIR}/data/agent_cards.json`。

**改造：** `handler.py` 删除 `_load_agent_cards()` 和 `_save_agent_cards()` 两个函数。所有引用改为调用 `agent_card.py` 的 `load_cards()`/`save_cards()` 接口。最终存储路径统一为 `config/agent_cards.json`。

```python
# handler.py — 删除以下两个函数
def _load_agent_cards() -> dict:    # ← 删除
def _save_agent_cards(cards) -> bool:  # ← 删除

# 所有 _load_agent_cards() 调用改为：
from . import agent_card as ac_mod
cards = ac_mod.get_all_cards()  # 替代 _load_agent_cards()

# 所有 _save_agent_cards() 调用改为：
ac_mod.save_cards()  # 替代 _save_agent_cards(cards)

# 注意：当前 _load_agent_cards() 返回的是 {agent_id: card} 的 dict
# ac_mod.get_all_cards() 返回同样的格式（_cards 就是 {agent_id: card}）
# 所以调用方的数据访问模式（cards[aid], card.get("pipeline_roles", []) 等）**完全不变**
```

**所有 15 处调用替换：**

| 行号 | 当前代码 | 替换为 |
|:----:|:---------|:-------|
| L881-894 | `def _load_agent_cards()` | ❌ 删除 |
| L899 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L912-922 | `def _save_agent_cards()` | ❌ 删除 |
| L927 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L952 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L1004 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L1369 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L1979 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L2315 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L2894 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3313 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3337 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3370 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3396 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3407 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |
| L3421 | `cards = _load_agent_cards()` | `cards = ac_mod.get_all_cards()` |

```diff
+# handler.py 顶部新增 import
+from . import agent_card as ac_mod

# _get_agent_display 函数中的调用
-def _get_agent_display(agent_id: str) -> str:
-    cards = _load_agent_cards()
+def _get_agent_display(agent_id: str) -> str:
+    cards = ac_mod.get_all_cards()
     ...
```

#### A2 — 格式统一：新 schema 定义

**位置：** `server/agent_card.py`

统一使用以下格式：

```json
{
  "arch-bot": {
    "display_name": "架构师",
    "pipeline_roles": ["arch"],
    "skills": ["write-tech-plan", "design-architecture"],
    "status": "online",
    "trigger_preference": {
      "mode": "mention",
      "mention_keyword": "架构师"
    },
    "capabilities": {
      "platforms": ["ws-bridge"],
      "can_code": false,
      "can_review": false,
      "can_deploy": false
    },
    "registered_at": 1782978000.0,
    "last_online": 1783065000.0
  }
}
```

| 字段 | 类型 | 说明 | 旧格式对应 |
|:-----|:-----|:------|:----------|
| `display_name` | str | 显示名 | `display_name` ✅ |
| `pipeline_roles` | str[] | 管线角色列表 | `role`（单值→数组包裹） |
| `skills` | str[] | 技能 ID 列表 | `skills`（对象数组→字符串数组） |
| `status` | str | online/offline/unknown | `state`（字段名不同） |
| `trigger_preference` | dict | 触发偏好 | `triggers`（数组→dict） |
| `capabilities` | dict | 能力声明 | 无对应，新建 |
| `registered_at` | float | 注册时间戳 | 无对应，新建 |
| `last_online` | float | 最后在线时间 | 无对应，新建 |

**改造：** `agent_card.py` 新增 `migrate_legacy_format()` 迁移函数：

```python
def migrate_legacy_format(cards: dict) -> dict:
    """将旧格式 Agent Card 转换为新格式。
    
    旧格式特征检测：
      - card 中有 "role" 字段（单字符串）→ 旧格式
      - card 中有 "pipeline_roles" 字段（列表）→ 已迁移
    """
    migrated = {}
    for agent_id, card in cards.items():
        if "pipeline_roles" in card:
            # 已是最新格式，保持
            migrated[agent_id] = card
            continue
        # 旧格式转换
        new_card = {
            "display_name": card.get("display_name", agent_id[:12]),
            "pipeline_roles": [card["role"]] if isinstance(card.get("role"), str) else card.get("roles", []),
            "skills": [s.get("id", s) if isinstance(s, dict) else s 
                      for s in card.get("skills", [])],
            "status": card.get("state", "unknown"),  # state → status
            "trigger_preference": {
                "mode": "mention",
                "mention_keyword": card.get("display_name", agent_id[:12]),
            },
        }
        # 如果旧格式有 triggers 字段，取第一个作为 mention_keyword
        old_triggers = card.get("triggers", [])
        if old_triggers:
            new_card["trigger_preference"]["mention_keyword"] = old_triggers[0]
        
        migrated[agent_id] = new_card
    
    return migrated
```

**调用时机：** 在 `load_cards()` 中，读取 JSON 后立即迁移并保存（一次性操作）：

```python
def load_cards() -> None:
    global _cards
    if _CARDS_PATH.exists():
        try:
            raw_data = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
            migrated = migrate_legacy_format(raw_data)
            if migrated != raw_data:  # 发生了迁移 → 写回去
                _cards = migrated
                save_cards()
            else:
                _cards = migrated
            logger.info("Loaded %d agent cards from %s", len(_cards), _CARDS_PATH)
        except (json.JSONDecodeError, OSError) as e:
            ...
```

#### A3 — handler.py 中 `_cmd_agent_card_set` 同步写入问题

**位置：** `server/handler.py` `_cmd_agent_card_set()`

当前 `_cmd_agent_card_set` 调用 `_save_agent_cards(cards)` 写 handler.py 自己的存储。改为调用 `ac_mod.save_cards()`：

```python
# 改造前
async def _cmd_agent_card_set(sender_id: str, params: dict) -> str:
    ...
    cards = _load_agent_cards()       # ← 改为 ac_mod.get_all_cards()
    ...
    if _save_agent_cards(cards):      # ← 改为 ac_mod.save_cards()
        ...

# 改造后
async def _cmd_agent_card_set(sender_id: str, params: dict) -> str:
    ...
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    card["pipeline_roles"] = [r.strip() for r in role_str.split(",") if r.strip()]
    if name:
        card["display_name"] = name
    if skills_str:
        card["skills"] = [s.strip() for s in skills_str.split(",") if s.strip()]
    card["status"] = card.get("status", "online")
    card["updated_at"] = time.time()
    cards[agent_id] = card

    if ac_mod.save_cards():
        _refresh_role_agent_map()  # 新增：set 后自动重建映射
        ...
```

> **关键注意：** `ac_mod.get_all_cards()` 返回的是 `_cards` dict 的引用——直接修改它会污染内部缓存。需要返回深拷贝，或者在 `_cmd_agent_card_set` 中显式写回。

```python
def get_all_cards() -> dict:
    """返回所有 Agent Card 的深拷贝，防止外部修改污染缓存。"""
    return copy.deepcopy(_cards)
```

---

### 方向 B（核心）：角色映射自动重建与热加载 🔴 P0

**核心思路：** 文件变动自动触发角色映射重建 + 启动时自动加载。去掉人工 `!agent_card reload` 的中间步骤。

#### B1 — 启动时自动加载 + 重建

**位置：** `server/handler.py` 启动初始化处

当前启动流程中，`load_cards()` 被调用但 `_refresh_role_agent_map()` 可能未被触发。

```python
# 改造：在启动时确保加载 + 重建
# 在 handler 初始化函数的合适位置（约 L400 附近）增加：
from . import agent_card as ac_mod
ac_mod.load_cards()
_refresh_role_agent_map()
logger.info("Agent cards loaded and role map refreshed at startup")
```

并且检查：
- `load_cards()` 是否已在 `if __name__ == "__main__":` 或早期初始化中被调用
- 如果 `_refresh_role_agent_map()` 已经在 `load_cards()` 之后调用，则跳过

#### B2 — 文件变动监听（轮询模式）

**位置：** `server/agent_card.py` 新增类

```python
import os
import time
import threading
import logging

logger = logging.getLogger("ws-bridge")


class CardFileWatcher:
    """轮询检测 agent_cards.json 文件变动，触发回调。
    
    使用简单轮询避免引入 inotify 依赖。——纯 Python 标准库。
    轮询间隔：5 秒。
    """
    
    def __init__(self, file_path, on_change=None):
        self._path = file_path
        self._on_change = on_change
        self._mtime = 0.0
        self._running = False
        self._thread = None
    
    def start(self):
        if not os.path.exists(self._path):
            logger.warning("CardFileWatcher: file %s not found, not starting", self._path)
            return
        self._mtime = os.path.getmtime(self._path)
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True, name="card-watcher")
        self._thread.start()
        logger.info("CardFileWatcher started for %s", self._path)
    
    def stop(self):
        self._running = False
    
    def _poll(self):
        while self._running:
            time.sleep(5)
            try:
                if os.path.exists(self._path):
                    mtime = os.path.getmtime(self._path)
                    if mtime != self._mtime:
                        self._mtime = mtime
                        logger.info("CardFileWatcher: file changed, reloading...")
                        if self._on_change:
                            self._on_change()
            except OSError:
                pass
```

**回调注册：** 在 handler.py 启动时注册 `_refresh_role_agent_map` 作为回调：

```python
# 启动时
watcher = ac_mod.CardFileWatcher(
    ac_mod.get_cards_path(),
    on_change=_refresh_role_agent_map
)
watcher.start()
```

**管理命令：** 新增 `!agent_card watch` 命令启动/停止监听器：

```python
async def _cmd_agent_card_watch(sender_id: str, params: dict) -> str:
    """启动/停止文件变动监听。
    用法：!agent_card watch [start|stop|status]
    """
    global _card_watcher
    sub = params.get("_positional", ["status"])[0]
    if sub == "start":
        if _card_watcher is None or not _card_watcher._running:
            _card_watcher = ac_mod.CardFileWatcher(
                ac_mod.get_cards_path(),
                on_change=_refresh_role_agent_map
            )
            _card_watcher.start()
            return "✅ 文件监听已启动"
        return "✅ 文件监听已在运行"
    elif sub == "stop":
        if _card_watcher:
            _card_watcher.stop()
            return "✅ 文件监听已停止"
        return "⚠️ 无运行中的文件监听"
    else:
        running = _card_watcher is not None and _card_watcher._running
        return f"📋 文件监听状态：{'🟢 运行中' if running else '🔴 已停止'}"
```

---

### 方向 C（辅助）：心跳 + 在线状态持久化 🟡 P1

**核心思路：** Agent 定期发送心跳，server 记录 `last_online` 时间戳，容器重建后恢复状态。

#### C1 — 心跳协议扩展

**位置：** `server/handler.py` WS 消息处理 + `shared/protocol.py`

在 `shared/protocol.py` 中定义心跳消息类型：

```python
# 已有类型不变，新增：
MSG_HEARTBEAT = "heartbeat"
```

```python
# handler.py 消息分派中处理心跳（约 L1000 附近）
if msg_type == MSG_HEARTBEAT:
    # 更新 Agent 在线时间戳
    agent_id = sender_id
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id)
    if card:
        card["last_online"] = time.time()
        card["status"] = "online"
        ac_mod.save_cards()
    return  # 不广播心跳消息
```

**心跳消息格式（Agent→Server）：**

```json
{"type": "heartbeat", "agent_id": "arch-bot"}
```

Server 不需要回复。心跳是单向的。

#### C2 — 离线自动标记

**位置：** `server/agent_card.py` 新增检查函数

```python
def mark_stale_offline(timeout: float = 300.0) -> int:
    """标记超过 timeout 秒无心跳的 Agent 为 offline。
    返回标记数量。
    """
    now = time.time()
    count = 0
    for aid, card in _cards.items():
        last = card.get("last_online", 0)
        if last > 0 and (now - last) > timeout and card.get("status") == "online":
            card["status"] = "offline"
            count += 1
    if count:
        save_cards()
    return count
```

定期在 watchdog 中调用（与 `pipeline_sync.py` 类似模式，每 120s）：

```python
# 在已有 watchdog 循环中增加
from . import agent_card as ac_mod
offline_count = ac_mod.mark_stale_offline()
if offline_count:
    logger.info("Marked %d agents offline due to heartbeat timeout", offline_count)
```

#### C3 — 启动时恢复在线状态

**位置：** `server/handler.py` 启动初始化

启动时不将所有 Agent 标记为 offline——保留文件中的 `last_online`。当 Agent 通过 WebSocket 连接时，自动将其 `status` 设为 `online`。

已有逻辑（WebSocket 连接处理中）：
```python
# 约 L1380 附近 — 连接建立时
if R63_ENABLE_AGENT_MAP:
    ...
    ac_mod.register_agent(agent_id, name, role)
```

这已经会在连接时更新 `last_online` 和 `status`。需要确认 `register_agent` 是否被正确调用——它在 `_handle_rollcall_ack` 和 WebSocket 连接回调中都有调用。

#### C4 — Agent 端心跳实现（建议）

Agent 侧（各 Gateway bot）需定期发送心跳消息：

```python
# 在 Gateway 插件的 message_loop 或定时器中
async def heartbeat_loop(ws):
    while True:
        await asyncio.sleep(60)  # 每 60 秒发一次
        try:
            await ws.send(json.dumps({"type": "heartbeat"}))
        except:
            break
```

**本轮范围限制：** 仅定义心跳协议和 server 端处理。Agent 端心跳由各 bot 自行实现（可推后到下轮）。

---

### 方向 D（顺手）：残留清理 🟢 P2

**位置：** `server/handler.py`

R66 验收中提到的 `_load_step_config()` 残留——当前有 14 处引用。其中 R66 的 `_get_step_config()` 函数需要先存在才能替换。

**检查方式：**

```bash
# 确认当前状态
grep -n '_load_step_config\|_get_step_config' server/handler.py

# 如果 _get_step_config 已存在：
#   → 将所有 _load_step_config() 替换为 _get_step_config(round_name)
#   如果需要 round_name，从当前作用域已有的 pstate/pconfig 获取

# 如果 _get_step_config 不存在（R66 尚未部署）：
#   → 本轮不清理，标注为「需 R66 部署后方可清理」
```

**如果 R66 已部署（_get_step_config 存在）：**

```python
# 替换模式示例
# 改造前
step_config = _load_step_config()

# 改造后（需要 round_name 上下文）
pstate = _PIPELINE_STATE.get(round_name, {})
step_config = _get_step_config(round_name)
```

| 行号 | 函数上下文 | round_name 来源 |
|:----:|:-----------|:----------------|
| L1291 | 管线相关函数 | 从调用方传入或 `pstate.get("round_name")` |
| L1417 | 同上 | 同上 |
| L1476 | 同上 | 同上 |
| L1759 | 同上 | 同上 |
| L1818 | 同上 | 同上 |
| L1832 | 同上 | 同上 |
| L1980 | 同上 | 同上 |
| L2209 | `_cmd_step_complete` | `round_name` 参数 |
| L2259 | `_cmd_step_complete` | `round_name` 参数 |
| L2815 | `_cmd_step_reject` | `round_name` 参数 |
| L2981 | `_cmd_step_handoff` | `round_name` 参数 |
| L3139 | `_cmd_pipeline_status` | `round_name` 参数 |
| L3275 | `_cmd_pipeline_activate` | `round_name` 参数 |

---

## 3. 验收标准

### 🎯 3.1 方向 A（存储统一 + 格式对齐）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | **`_load/save_agent_cards()` 从 handler.py 中删除** | 两个函数不再存在 | `grep -n '_load_agent_cards\|_save_agent_cards' server/handler.py` 零匹配 |
| ✅-2 | **所有引用替换为 `ac_mod.get_all_cards()` / `ac_mod.save_cards()`** | handler.py 零运行时错误 | 启动后 `!agent_card list` 正常输出 |
| ✅-3 | **旧 `config/agent_cards.json` 数据迁移到新格式** | 启动后文件被重写为新格式，`role` 字段 → `pipeline_roles` 数组 | 查看 `config/agent_cards.json` 确认格式 |
| ✅-4 | **`ac_mod.get_all_cards()` 返回深拷贝，外部修改不污染缓存** | `_cmd_agent_card_set` 修改的 dict 不影响 `_cards` | 代码审查 `get_all_cards` 实现 |
| ✅-5 | **`!agent_card set` + `!agent_card unset` 写入统一路径** | 操作后文件变更在 `config/agent_cards.json` 中可见 | 执行 set/unset → 检查文件内容 |
| ✅-6 | **启动无任何 Agent Card 相关异常** | server 启动日志不报 `FileNotFoundError` | 启动后检查日志 |

### 🎯 3.2 方向 B（角色映射自动重建 + 热加载）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-7 | **启动时角色映射自动重建** | server 启动后 `!agent_role_map` 输出非空 | 启动后立刻执行命令 |
| ✅-8 | **编辑 `config/agent_cards.json` 后角色映射自动更新（轮询模式）** | 修改文件 → 5 秒内 `_refresh_role_agent_map()` 被调用 | 修改文件 → `!agent_role_map` 确认变化 |
| ✅-9 | **`!agent_card watch` 命令正常** | start/stop/status 三个子命令工作 | 实测 |
| ✅-10 | **卡变动监听不阻塞 Server 主循环** | 监听器在 daemon 线程中，server 重启时不残留 | 代码审查 `daemon=True` |

### 🎯 3.3 方向 C（心跳 + 在线状态持久化）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-11 | **心跳消息被 server 正确接收** | 收到后更新 `last_online` 和 `status` | 发送模拟心跳 → 检查文件 |
| ✅-12 | **心跳消息不广播到工作室** | 其他 bot 不收到心跳消息 | 检查 `!_connections` 消息分派逻辑 |
| ✅-13 | **离线自动标记工作** | 超过 300s 无心跳的 Agent 被标记为 offline | `mark_stale_offline()` 实测 |
| ✅-14 | **WS 连接时自动恢复 online 状态** | Agent 重连后 `status` 更新为 `online` | 断开 → 重连 → 检查状态 |

### 🎯 3.4 方向 D（R66 残留清理）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-15 | **`_load_step_config()` 零运行时引用**（如果 R66 已部署） | 所有 14 处替换完成 | `grep -n '_load_step_config' server/handler.py` 仅在函数定义处出现 |
| ✅-15a | **如果 R66 未部署，`_get_step_config` 不存在** | 方向 D 标注为「等待 R66 部署」 | `grep '_get_step_config'` 零匹配时说明 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| Agent 端心跳实现 | Gateway bot 侧发送心跳的代码 | 本轮只定义 server 端处理。Agent 端由各 bot 自行实现 |
| A2A 协议对齐 | Agent Card schema 对齐 Google A2A 标准 | 其专属轮次 |
| Web UI Agent 管理页面 | 在 Web 端增加 Agent Card 管理界面 | 其专属轮次 |
| RBAC 权限体系 | 角色→权限映射表 | 其专属轮次（需求架构 §七 6.1） |
| 管线仪表盘 | Step 进度条可视化 | 其专属轮次 |
| 多个活跃管线 | 同时运行多个独立管线 | 其专属轮次 |
| Gateway 插件 | `gateway-plugin/` 目录 | 本轮不动 |
| `config/agent_cards.json` 增加图形化编辑 | — | 超出本轮 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 15min |
| **2** | 👷 Arch | 技术方案 + 改动设计 | 20min |
| **3** | 👨‍💻 Dev | 编码实现 | 30min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/agent_card.py` | **修改** — 新增 `migrate_legacy_format()` + `get_cards_path()` + `CardFileWatcher` 类 + `mark_stale_offline()` + `get_all_cards()` 深拷贝 + `load_cards()` 自动迁移 | ~80 行净增 |
| `server/handler.py` | **修改** — 删除 `_load/save_agent_cards()`（~30 行删除）+ 15 处替换引用（~15 行修改）+ 新增 `_cmd_agent_card_watch`（~30 行）+ B1 启动加载（~5 行）+ C1 心跳处理（~15 行） | ~35 行净减 |
| `shared/protocol.py` | **修改** — 新增 `MSG_HEARTBEAT = "heartbeat"` | +1 行 |
| `docs/R67/*` | **新增** — 需求文档 + WORK_PLAN + 技术方案 + 测试报告 | ~200 行 |
| **合计** | | **~50 行净改** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `ac_mod.get_all_cards()` 返回引用而非副本 → handler.py 中修改污染缓存 | 配置变更时状态不一致 | 明确返回 `copy.deepcopy(_cards)` |
| 旧格式迁移意外修改了不在预期内的字段 | 数据丢失 | 迁移函数只处理已知字段，未知字段保留 |
| 文件变动监听 5s 轮询不够及时 | 修改后需 5s 才生效 | 可接受——管理员手动修改文件比这更慢 |
| `_load_step_config()` 替换需要 `round_name` 但某些函数上下文中没有 | 编译错误或运行时崩溃 | 逐个检查每个调用位置，从已有变量提取 `round_name` |

---

## 6. 脱敏检查清单

- [ ] docs/R67/*.md 零内部名残留
- [ ] `grep -n '内部名模式' docs/R67/*.md` 零匹配
- [ ] handler.py diff 零内部 URL/端口泄露
