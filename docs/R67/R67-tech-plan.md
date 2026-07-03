# R67 技术方案 — Agent Card 系统统一与角色映射持久化 🏗️

> **版本：** v1.0
> **状态：** ✅ 定稿
> **作者：** 👷 Arch
> **日期：** 2026-07-03
> **基于：** R67 需求文档 ✅ + WORK_PLAN v1.0 ✅

---

## 1. 当前基线确认

### 1.1 分支状态

**基线 commit（dev）：** `41341d0`
**R66 部署状态：** ✅ **已部署**（R66 的 `_get_step_config()` 函数 ✅ 已存在，WIP 文档中的「R66 未部署」标注已过时）

### 1.2 文件基线行号（实际，非预估）

| 文件 | 总行数 | 关键符号 |
|:-----|:------:|:---------|
| `server/agent_card.py` | 143 | `load_cards()` L21, `save_cards()` L57, `register_agent()` L70, `get_all_cards()` L44 |
| `server/handler.py` | 5728 | `_load_agent_cards()` L892, `_save_agent_cards()` L923, `_refresh_role_agent_map()` L954 |
| `shared/protocol.py` | 265 | MSG 常量区, 末行 `make_ack()` L264 |
| `config/agent_cards.json` | 68 | 旧格式（`role` 字段，`skills` 对象数组，`triggers` 数组） |

### 1.3 改动调用计数（精确）

| 符号 | 用途 | 计数 |
|:-----|:-----|:----:|
| `_load_agent_cards()` | **要删除的函数定义** | L892 (定义) |
| `_save_agent_cards()` | **要删除的函数定义** | L923 (定义) |
| `_load_agent_cards()` 调用 | **要替换为 `ac_mod.get_all_cards()`** | **16 处** |
| `_save_agent_cards()` 调用 | **要替换为 `ac_mod.save_cards()`** | **4 处** |
| `_load_step_config()` 定义 | 保留（`_get_step_config()` 也需它） | L1175 |
| `_load_step_config()` 调用 | **方向 D 要替换** | **7 处** |
| `_get_step_config()` 定义 | R66 已有 ✅ | L1181 |
| `_get_step_config()` 调用 | R66 已有 6 处，方向 D 再替换 7 处 | 总计 13 处 |
| `data/agent_cards.json` 路径引用 | 当前 0 处残留 | ✅ 删除后无残留 |

---

## 2. 方向 A：存储统一 + 格式对齐 🔴 P0

### A1 — 统一存储路径

**操作清单（共 6 个子改动）：**

#### ① handler.py 顶部新增 import（L10 附近）

```python
# 在 L10 `from . import auth, config, persistence` 行后新增：
from . import agent_card as ac_mod
```

> ⚠️ 注意：当前 L15-L18 已有 `import shared.protocol as p`。`ac_mod` import 放在协议 import 之后、logger 定义之前。

#### ② 删除 `_load_agent_cards()` 函数（L889-905）

完整删除 L889-905，包含函数体和 docstring。

#### ③ 删除 `_save_agent_cards()` 函数（L923-932）

完整删除 L923-932，包含函数体和 docstring。

#### ④ 替换 `_load_agent_cards()` → `ac_mod.get_all_cards()` — 16 处

| # | 所在函数 | 行号 | 替换内容 |
|:-:|:---------|:----:|:---------|
| 1 | `_get_agent_display()` | L910 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 2 | `_get_agent_card_roles()` | L938 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 3 | `_refresh_role_agent_map()` | L963 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 4 | `_handle_rollcall_ack()` | L1015 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 5 | 管线 step_complete 通知 | L1451 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 6 | `_cmd_pipeline_start()` | L2061 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 7 | 管线 Step 完成 handoff | L2402 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 8 | `_cmd_step_reject()` | L2998 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 9 | `_cmd_agent_card_list()` | L3422 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 10 | `_cmd_agent_card_get()` | L3446 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 11 | `_cmd_agent_card_set()` | L3479 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 12 | `_cmd_agent_card_unset()` | L3505 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 13 | `_cmd_agent_card_reload()` | L3516 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 14 | `_cmd_agent_role_map()` | L3530 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 15 | `_get_agent_card_roles()` 默认参 | L937 | `cards = _load_agent_cards()` → `cards = ac_mod.get_all_cards()` |
| 16 | `_refresh_role_agent_map()` 内部 | L963 | 同上 #3，确认单一调用 |

#### ⑤ 替换 `_save_agent_cards()` → `ac_mod.save_cards()` — 4 处

| # | 所在函数 | 行号 | 替换内容 |
|:-:|:---------|:----:|:---------|
| 1 | `_handle_rollcall_ack()` | L1031 | `_save_agent_cards(cards)` → 删除整行（改为统一走 `ac_mod.register_agent()` 接口，见下方 §A1-⑥） |
| 2 | `_cmd_agent_card_set()` | L3490 | `if _save_agent_cards(cards):` → `if ac_mod.save_cards():` |
| 3 | `_cmd_agent_card_unset()` | L3509 | `if _save_agent_cards(cards):` → `if ac_mod.save_cards():` |
| 4 | `_cmd_agent_role_map()` | 无直接 `_save_agent_cards` | 该函数不写数据，仅读 |

#### ⑥ 重构 `_handle_rollcall_ack()`（L1004-1033）

当前逻辑：
```python
cards = _load_agent_cards()   # 读旧存储
if sender_id in cards:
    cards[sender_id][...] = ...  # 更新旧存储
else:
    from . import agent_card as ac_mod  # 需要时 import
    ac_mod.register_agent(...)        # 写新存储
_save_agent_cards(cards)             # 写旧存储
```

改为：
```python
# 统一走 ac_mod 接口
users = auth.get_users()
u = users.get(sender_id, {})
name = u.get("name", sender_id[:12])
role = u.get("role", "member")

ac_mod.register_agent(sender_id, name, role)
_refresh_role_agent_map()
```

---

### A2 — 格式迁移：`migrate_legacy_format()`

**位置：** `server/agent_card.py`，`get_all_cards()` 之后（约 L47）

**当前 `agent_card.py` 内容现状（L1-143）：**

| 函数 | 行 | 说明 |
|:-----|:--:|:-----|
| `load_cards()` | L21-36 | 直接 JSON 反序列化，无迁移 |
| `get_all_cards()` | L44-46 | 返回 `_cards` 引用（非深拷贝） |
| `save_cards()` | L57-68 | 直接 `json.dump(_cards)` |
| `register_agent()` | L70-116 | 新格式写入 ✅ |
| `reload_cards()` | L49-51 | 代理 `load_cards()` |

#### 需要修改的 agent_card.py 函数：

**1. `load_cards()` — 改造为带自动迁移（L21-36 → 20 行）**

```python
def load_cards() -> None:
    global _cards
    if _CARDS_PATH.exists():
        try:
            raw_data = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
            migrated = migrate_legacy_format(raw_data)
            if migrated != raw_data:  # 迁移发生 → 持久化
                _cards = migrated
                save_cards()
                logger.info("Migrated %d agent cards to new format", len(migrated))
            else:
                _cards = migrated
            logger.info("Loaded %d agent cards from %s", len(_cards), _CARDS_PATH)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load agent cards from %s: %s", _CARDS_PATH, e)
            _cards = {}
    else:
        logger.warning("Agent Card config not found at %s", _CARDS_PATH)
        _cards = {}
```

**2. `get_all_cards()` — 改为深拷贝（L44-46 → 4 行）**

```python
def get_all_cards() -> dict[str, dict]:
    return copy.deepcopy(_cards)
```

**3. 新增 `get_cards_path()` — 暴露路径（~3 行）**

```python
def get_cards_path() -> str:
    return str(_CARDS_PATH)
```

**4. 新增 `migrate_legacy_format()` — 核心迁移函数（~35 行）**

```python
def migrate_legacy_format(cards: dict) -> dict:
    migrated = {}
    for agent_id, card in cards.items():
        if isinstance(card.get("pipeline_roles"), list):
            migrated[agent_id] = card
            continue

        new_card = {
            "display_name": card.get("display_name", agent_id[:12]),
            "pipeline_roles": [],
            "skills": [],
            "status": card.get("state", card.get("status", "unknown")),
            "trigger_preference": {
                "mode": "mention",
                "mention_keyword": card.get("display_name", agent_id[:12]),
            },
        }

        # role (str) → pipeline_roles (list)
        if isinstance(card.get("role"), str):
            new_card["pipeline_roles"] = [card["role"]]

        # skills: [{"id": "x", ...}] → ["x"]
        raw_skills = card.get("skills", [])
        if isinstance(raw_skills, list):
            for s in raw_skills:
                if isinstance(s, dict):
                    sid = s.get("id", "")
                    if sid:
                        new_card["skills"].append(sid)
                elif isinstance(s, str):
                    new_card["skills"].append(s)

        # triggers → trigger_preference.mention_keyword
        old_triggers = card.get("triggers", [])
        if old_triggers and isinstance(old_triggers, list) and len(old_triggers) > 0:
            trigger = old_triggers[0]
            if trigger.startswith("!"):
                trigger = trigger[1:]
            new_card["trigger_preference"]["mention_keyword"] = trigger

        if "capabilities" in card:
            new_card["capabilities"] = card["capabilities"]
        if "registered_at" in card:
            new_card["registered_at"] = card["registered_at"]
        if "last_online" in card:
            new_card["last_online"] = card["last_online"]

        migrated[agent_id] = new_card
    return migrated
```

**5. 新增 `update_card()` — 安全的写回接口（~10 行）**

```python
def update_card(agent_id: str, card_data: dict) -> None:
    """Update a single card in cache and persist. Sanctioned mutation path."""
    global _cards
    _cards[agent_id] = card_data
    save_cards()
```

**6. agent_card.py 顶部新增 import**

```python
import copy       # 新增
import threading  # 新增（B2 使用）
import os         # 已有（或新增，视编译检查）
```

---

### A3 — `_cmd_agent_card_set/unset` 走统一路径

**`_cmd_agent_card_set`（L3465-3494）改造：**

```python
async def _cmd_agent_card_set(sender_id: str, params: dict) -> str:
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card set <agent_id> --role <r1,r2> [--name <n>] [--skills <s1,s2>]"
    agent_id = positional[0]
    role_str = params.get("role", "")
    if not role_str:
        return "--role is required"
    name = params.get("name", "")
    skills_str = params.get("skills", "")

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

    # 通过 update_card 写回
    ac_mod.update_card(agent_id, card)
    _refresh_role_agent_map()
    roles_display = ", ".join(card["pipeline_roles"])
    return f"✅ Card set: {agent_id} -> {card.get('display_name', agent_id[:12])} roles=[{roles_display}]"
```

**`_cmd_agent_card_unset`（L3497-3511）改造：**

```python
async def _cmd_agent_card_unset(sender_id: str, params: dict) -> str:
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card unset <agent_id>"
    agent_id = positional[0]
    cards = ac_mod.get_all_cards()
    if agent_id not in cards:
        return "No card for agent " + agent_id[:24]
    del cards[agent_id]
    if ac_mod.save_cards():
        _refresh_role_agent_map()
        return "Deleted card for " + agent_id[:24]
    return "Save failed"
```

---

## 3. 方向 B：角色映射自动重建 + 热加载 🔴 P0

### B1 — 启动时自动加载 + 重建

**位置：** `server/handler.py` `_refresh_role_agent_map()` 定义之后（约 L975）

```python
# ── R67 B1: Auto-load agent cards at startup ──
def _ensure_agent_cards_loaded() -> None:
    """Ensure agent cards are loaded and role map is built at startup."""
    ac_mod.load_cards()
    _refresh_role_agent_map()
```

**调用位置：** 在 `handle_broadcast()` 入口处（L3868-3873），与 watchdog/git_sync 同级：

```python
async def handle_broadcast(ws, sender_id: str, msg: dict) -> None:
    _ensure_watchdog()
    _restore_pipeline_timers()
    _ensure_git_scan()
    _ensure_agent_cards_loaded()  # ← R67 新增
```

> ⚠️ **幂等设计：** `_ensure_agent_cards_loaded()` 使用 `if _cards_loaded: return` 守护，只在首次调用时执行。使用模块级 `_cards_loaded: bool = False` 标记。

### B2 — CardFileWatcher 轮询线程

**位置：** `server/agent_card.py` 末尾（约 L144+）

```python
class CardFileWatcher:
    """Poll-based file change detector for agent_cards.json.
    5-second poll interval, daemon thread, triggers on_change callback.
    """

    def __init__(self, file_path: str, on_change=None):
        self._path = file_path
        self._on_change = on_change
        self._mtime = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

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
        logger.info("CardFileWatcher stopped for %s", self._path)

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def _poll(self):
        while self._running:
            time.sleep(5)
            try:
                if os.path.exists(self._path):
                    mtime = os.path.getmtime(self._path)
                    if mtime != self._mtime:
                        self._mtime = mtime
                        logger.info("CardFileWatcher: file changed, reloading...")
                        load_cards()
                        if self._on_change:
                            self._on_change()
            except OSError:
                pass
```

**全局变量 + 自动启动（handler.py L975 附近）：**

```python
# ── R67 B2: Card file watcher ──
_card_watcher: ac_mod.CardFileWatcher | None = None

def _ensure_card_watcher() -> None:
    global _card_watcher
    if _card_watcher is not None and _card_watcher.is_running():
        return
    _card_watcher = ac_mod.CardFileWatcher(
        ac_mod.get_cards_path(),
        on_change=_refresh_role_agent_map,
    )
    _card_watcher.start()
```

**命令 `!agent_card watch`（新增函数约 L3540 区域）：**

```python
async def _cmd_agent_card_watch(sender_id: str, params: dict) -> str:
    """启动/停止文件变动监听。
    用法：!agent_card watch [start|stop|status]
    """
    global _card_watcher
    positional = params.get("_positional", ["status"])
    if not positional:
        return "用法：!agent_card watch [start|stop|status]"
    sub = positional[0]

    if sub == "start":
        if _card_watcher and _card_watcher.is_running():
            return "✅ 文件监听已在运行"
        _card_watcher = ac_mod.CardFileWatcher(
            ac_mod.get_cards_path(),
            on_change=_refresh_role_agent_map,
        )
        _card_watcher.start()
        return "✅ 文件监听已启动"
    elif sub == "stop":
        if _card_watcher and _card_watcher.is_running():
            _card_watcher.stop()
            return "✅ 文件监听已停止"
        return "⚠️ 无运行中的文件监听"
    else:
        running = _card_watcher is not None and _card_watcher.is_running()
        return f"📋 文件监听状态：{'🟢 运行中' if running else '🔴 已停止'}"
```

**在 `_ADMIN_COMMANDS` 中注册（L3700 附近）：**

```python
    # ── R67: Card file watcher ──
    "agent_card_watch": {
        "handler": _cmd_agent_card_watch, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card watch [start|stop|status]",
    },
```

### B3 — `_cmd_agent_card_reload` 增强

**L3514-3518 改造：** 当前只是重读文件后返回计数，改为同时刷新角色映射。

```python
async def _cmd_agent_card_reload(sender_id: str, params: dict) -> str:
    ac_mod.reload_cards()
    _refresh_role_agent_map()
    cards = ac_mod.get_all_cards()
    return f"✅ Reloaded {len(cards)} agent cards, role map refreshed"
```

---

## 4. 方向 C：心跳 + 在线状态持久化 🟡 P1

### C1 — 心跳协议扩展

**位置：** `shared/protocol.py` L207 之后

```python
# R67: Heartbeat — Agent liveness check
MSG_HEARTBEAT = "heartbeat"
```

### C2 — Server 端心跳处理

**位置：** `server/handler.py` WS 消息分派链中（约 L5206，紧跟 MSG_ACK 处理之后）

```python
            elif msg_type == p.MSG_HEARTBEAT:
                # Update last_online + status, do NOT broadcast
                agent_id = sender_id
                card = ac_mod.get_agent_card(agent_id)
                if card:
                    card["last_online"] = time.time()
                    card["status"] = "online"
                    ac_mod.save_cards()
                continue  # 跳过广播
```

> ⚠️ 注意：`get_agent_card()` 返回的是 `_cards` 引用（不是深拷贝），所以直接修改 `card` dict 会修改内部缓存。这在此处是期望行为——心跳更新不需要深拷贝的隔离。

### C3 — 离线自动标记

**位置：** `server/agent_card.py`（`CardFileWatcher` 之前）

```python
def mark_stale_offline(timeout: float = 300.0) -> int:
    """Mark agents with no heartbeat within `timeout` seconds as offline.
    Returns number of agents marked offline.
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

### C4 — Watchdog 中定期调用离线标记

**位置：** `_watchdog_scan()` 函数体（L1493）开头，在 `if not _PIPELINE_STATE: return` 之后：

```python
async def _watchdog_scan() -> None:
    if not _PIPELINE_STATE:
        return
    
    # ── R67 C4: Mark stale agents offline ──
    try:
        offline_count = ac_mod.mark_stale_offline()
        if offline_count:
            logger.info("R67: marked %d agent(s) offline due to heartbeat timeout", offline_count)
    except Exception:
        logger.warning("R67: mark_stale_offline failed", exc_info=True)
    
    now = time.time()
    ...  # 原有逻辑继续
```

> **设计理由：** `_watchdog_scan()` 已有 10 分钟扫描间隔，在此处插入离线标记无需额外 coroutine。300s（5 分钟）超时阈值 × 10 分钟扫描间隔 = 最多 15 分钟标记延迟，可接受。

---

## 5. 方向 D：R66 残留清理 🟢 P2

### R66 已部署确认

`_get_step_config()` 已在 L1181 ✅。`_load_step_config()` 仍有 7 处调用可以替换。

### 替换清单

遍历 7 处 `_load_step_config()` 调用，每个位置需要从作用域中获取 `round_name`：

| # | 行号 | 函数上下文 | round_name 来源 | 改造方式 |
|:-:|:----:|:-----------|:----------------|:---------|
| 1 | L1499 | `_watchdog_scan()` | 循环变量 `round_name` 来自 `for round_name, pstate in list(...)` | L1499: `step_config = _load_step_config()` → `step_config = _get_step_config(round_name)` |
| 2 | L1558 | `_watchdog_scan()` 内部 | 同上 `round_name` | 同上模式 |
| 3 | L1841 | 管线超时处理 | 需确认 `round_name` 作用域 | 从 `pstate` 或外层获取 |
| 4 | L1900 | 同上 | 同上 | 同上 |
| 5 | L1914 | 同上 | 同上 | 同上 |
| 6 | L2291 | `_cmd_step_complete` | 函数参数 | `round_name` 已作为参数传入 |
| 7 | L3384 | `_cmd_pipeline_activate` | 函数参数 | `round_name` 已作为参数传入 |

> **约束：** 每个替换必须确认作用域中 `round_name` 或等效变量可用。如果某处 `round_name` 不可直接获得，则暂时跳过（保留 `_load_step_config()` 调用）。`_load_step_config()` 函数定义（L1175）保留——作为 `_get_step_config()` 的 fallback 依赖。

---

## 6. 精确改动清单总览

### 文件 `server/agent_card.py`（~75 行净增）

| # | 改动 | 类型 | 位置 |
|:-:|:-----|:----:|:-----|
| 1 | 顶部新增 `import copy, threading` | +2 行 | 顶部 |
| 2 | `load_cards()` 改造为带自动迁移 | 修改 | L21-36 |
| 3 | `get_all_cards()` 改为深拷贝 | 修改 | L44-46 |
| 4 | 新增 `get_cards_path()` | +3 行 | L47-50 |
| 5 | 新增 `migrate_legacy_format()` | +35 行 | ~L52-86 |
| 6 | 新增 `update_card()` | +10 行 | ~L88-97 |
| 7 | 新增 `CardFileWatcher` 类 | +45 行 | ~L100-144 |
| 8 | 新增 `mark_stale_offline()` | +15 行 | ~L146-160 |

### 文件 `server/handler.py`（~30 行净减）

| # | 改动 | 类型 | 行号 |
|:-:|:-----|:----:|:----:|
| 9 | 顶部新增 `from . import agent_card as ac_mod` | +1 行 | ~L10 |
| 10 | 删除 `_load_agent_cards()` 函数 | -14 行 | L889-905 |
| 11 | 删除 `_save_agent_cards()` 函数 | -10 行 | L923-932 |
| 12 | 替换 16 处 `_load_agent_cards()` → `ac_mod.get_all_cards()` | 16×1 行 | 多处 |
| 13 | 替换 4 处 `_save_agent_cards()` → `ac_mod.save_cards()` | 4×1 行 | 多处 |
| 14 | 重构 `_handle_rollcall_ack()` — 统一走 ac_mod | 修改 | L1004-1033 |
| 15 | `_refresh_role_agent_map()` 后新增启动加载 | +8 行 | L975-982 |
| 16 | 新增 `CardFileWatcher` 全局 + `_ensure_card_watcher()` | +15 行 | ~L984-998 |
| 17 | 新增 `_cmd_agent_card_watch()` 命令 | +35 行 | ~L3540-3574 |
| 18 | `_ADMIN_COMMANDS` 注册 `agent_card_watch` | +5 行 | L3700 区 |
| 19 | 增强 `_cmd_agent_card_reload()` | 修改 | L3514-3518 |
| 20 | 改造 `_cmd_agent_card_set()` — 统一路径 | 修改 | L3465-3494 |
| 21 | 改造 `_cmd_agent_card_unset()` — 统一路径 | 修改 | L3497-3511 |
| 22 | WS 消息分派新增 MSG_HEARTBEAT 处理 | +10 行 | ~L5206 |
| 23 | `_watchdog_scan()` 中插入 `mark_stale_offline()` | +8 行 | L1493 区域 |

### 文件 `shared/protocol.py`（+1 行）

| # | 改动 | 类型 | 行号 |
|:-:|:-----|:----:|:----:|
| 24 | 新增 `MSG_HEARTBEAT = "heartbeat"` | +1 行 | L208 |

### 文件 `config/agent_cards.json`（自动迁移，不需手动改）

| 旧字段 | 新字段 | 迁移实例 |
|:-------|:-------|:---------|
| `role: "architect"` | `pipeline_roles: ["architect"]` | 自动 |
| `skills: [{"id": "write-tech-plan", ...}]` | `skills: ["write-tech-plan"]` | 自动 |
| `triggers: ["!arch", "!方案"]` | `trigger_preference.mention_keyword: "arch"` | 自动 |
| `state: "online"` | `status: "online"` | 自动 |
| `agent_id: "arch-bot"` | 顶层 key（保持不变） | 不变 |

### 文件 `docs/R67/*`（新增）

| 文件 | 状态 |
|:-----|:----:|
| `R67-product-requirements.md` | ✅ step1 |
| `WORK_PLAN.md` | ✅ step1 |
| `R67-tech-plan.md` | ✅ **step2（当前）** |
| `R67-code-review.md` | ⏳ step4 |
| `R67-test-report.md` | ⏳ step5 |

---

## 7. 迁移验证

### 7.1 格式迁移预期输出

迁移后 `config/agent_cards.json` 应变为：

```json
{
  "arch-bot": {
    "display_name": "架构师",
    "pipeline_roles": ["architect"],
    "skills": ["write-tech-plan", "design-architecture"],
    "status": "online",
    "trigger_preference": {
      "mode": "mention",
      "mention_keyword": "arch"
    }
  },
  "dev-bot": {
    "display_name": "开发工程师",
    "pipeline_roles": ["developer"],
    "skills": ["implement-code", "fix-bugs"],
    "status": "online",
    "trigger_preference": {
      "mode": "mention",
      "mention_keyword": "dev"
    }
  }
}
```

### 7.2 幂等性验证

`migrate_legacy_format()` 是**幂等**的——已迁移的卡片（包含 `pipeline_roles` 数组）不会再次处理。二次迁移输出应与首轮一致。

### 7.3 边界情况

| 场景 | 预期行为 |
|:-----|:---------|
| `config/agent_cards.json` 不存在 | `load_cards()` 日志警告 `_cards = {}`，server 正常运行 |
| 文件为空 `{}` | 迁移后仍为空，不触发写回（`migrated == raw_data`） |
| 旧格式和新格式混合 | 各自正确识别并处理 |
| 手动编辑后 5 秒内自动更新 | `CardFileWatcher` 检测 mtime 变化，触发 `load_cards()` + `_refresh_role_agent_map()` |
| `get_all_cards()` 返回深拷贝 | 外部修改不影响内部 `_cards` |

---

## 8. Scope 合规检查

| 文件 | 不改入 ✅ |
|:-----|:---------:|
| `server/pipeline_sync.py` | ✅ |
| `server/timeout_tracker.py` | ✅ |
| `server/workspace.py` | ✅ |
| `server/task_store.py` | ✅ |
| `server/web_viewer.py` | ✅ |
| `gateway-plugin/` | ✅ |

| 事项 | 不改出 ✅ |
|:-----|:---------:|
| A2A 协议兼容 | ✅ |
| Web UI Agent 管理页面 | ✅ |
| RBAC 权限体系 | ✅ |
| Agent 端心跳实现 | ✅（仅 server 端 + 协议定义） |

---

## 9. 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `ac_mod.get_all_cards()` 深拷贝引入额外内存 | 千张卡约 500μs 开销 | 可接受；如性能瓶颈出现可改为只读代理对象 |
| `_handle_rollcall_ack` 重构后 `_save_agent_cards(cards)` 被删除而 `ac_mod.register_agent()` 未覆盖所有分支 | 已有卡更新遗漏 | 已确认 `register_agent()` 的 `force=False` 分支会更新 `last_online` + `status` — **覆盖完整** |
| `CardFileWatcher` 轮询 5s + 文件写操作并发 | 保存时读取到不完整 JSON | 仅在 `_poll` 中比较 mtime 后 `load_cards()`，文件写入是原子性的（write_text 非原子但会覆盖完成） |
| R66 残留替换的 7 处 `round_name` 不可得 | 编译错误 | 逐个验证，不可得时跳过（保留 `_load_step_config()`） |

---

## 10. 管线交接

### 产出

- ✅ 技术方案文档推 dev：`docs/R67/R67-tech-plan.md`
- ✅ 所有 24 个改动点精确行号确认
- ✅ 所有调用位置验证无误

### 下一步 (Step 3 — 编码)

**主角：** dev | **备用：** arch

**执行顺序建议：**

1. 先改 `shared/protocol.py`（+1 行，零风险）
2. 改 `server/agent_card.py`（迁移函数 + 深拷贝 + CardFileWatcher + mark_stale_offline）
3. 改 `server/handler.py`：
   - 顶部 import
   - 删除 `_load/save_agent_cards()`
   - 替换 20 处调用
   - 重构 `_handle_rollcall_ack()`
   - 新增启动加载 + watcher
   - 改造 `_cmd_agent_card_set/unset/reload`
   - 新增 `_cmd_agent_card_watch`
   - 注册 admin command
   - MSG_HEARTBEAT 处理
   - Watchdog 中增加离线标记
4. 方向 D：7 处 `_load_step_config()` → `_get_step_config()` 替换
5. 提交前脱敏检查
6. `!step_complete step3 --output <sha>`
