# R63 技术方案 — 多 Agent 协作基础设施（过渡轮次）

> **版本：** v1.0
> **状态：** ✅ 定稿
> **架构师：** 🏗️ arch
> **日期：** 2026-07-01
> **基于：** R63 产品需求 v1.0 ✅ + WORK_PLAN v1.0 ✅
> **本方案涉及改动范围：** `server/handler.py` + `server/timeout_tracker.py`(新增) + `server/agent_card.py` + `server/config.py`

---

## 0. 前置发现：R62 代码状态评估

需求文档 §2 注明「R62 `_PIPELINE_CONFIG` 和 frontmatter 解析器未部署到代码」——**经代码审计，实际情况不同：**

| 组件 | 需求所述 | 实际代码 | 结论 |
|:-----|:---------|:---------|:-----|
| `_PIPELINE_CONFIG: dict[str, dict] = {}` | ❌ 未部署 | `handler.py` L47 ✅ | **已部署** |
| `_parse_frontmatter(content) -> dict` | ❌ 未部署 | `handler.py` L960 ✅ | **已部署** |
| `_build_pipeline_config(fm, round, urls) -> dict` | ❌ 未部署 | `handler.py` L1003 ✅ | **已部署** |
| `_build_fallback_config(round, urls) -> dict` | ❌ 未部署 | `handler.py` L1023 ✅ | **已部署** |
| `NoFrontmatterError` / `_parse_scalar` | ❌ 未部署 | `handler.py` L930 / L939 ✅ | **已部署** |
| `_cmd_pipeline_start` frontmatter 集成 | ❌ 未部署 | `handler.py` L1411-1441 ✅ | **已部署** |
| `_cmd_step_complete` 从 config 读参数 | ❌ 未部署 | `handler.py` L1703-1708 ✅ | **已部署** |
| `_clear_pipeline_state()` 不清 config | ❌ 未部署 | `handler.py` L1075-1080 ✅ | **已部署** |

**结论：** 方向 A5（R62 `_PIPELINE_CONFIG` 落地）**已完成 90%**。R63 的编码阶段只需验证确认，无需重新实现。验收项 ✅-23~✅-30 可在 Phase 1 快速验证通过。

### 剩余缺口

| 组件 | 代码状态 | R63 所需动作 |
|:-----|:---------|:-------------|
| `timeout_tracker.py` | ❌ 不存在 | **新增 ~80 行** |
| 倒计时集成（status/超时触发/step切换） | ❌ 未实现 | **~40 行注入 handler.py** |
| `_ROLE_AGENT_MAP` + `get_agents_by_role()` | ❌ 不存在（`_find_agents_by_role` L918 存在但未被调用） | **~20 行** |
| 点名注册逻辑 | ❌ 不存在 | **~25 行** |
| ACK 状态机 | ❌ 不存在 | **~55 行** |
| 退化开关 | ❌ 不存在 | **~10 行 config + ~10 行 handler** |
| `from_name` 检查 | `PIPELINE_PM_NAME` 已用于 kickoff | **~5 行检查覆盖** |

**重估总改动量：** ~245 行（比 WORK_PLAN 预估 515 行减少 ~270 行，因为 R62 基础已就位）

---

## 1. `timeout_tracker.py` API 设计

### 1.1 模块定位

**新增文件：** `server/timeout_tracker.py`

独立模块，与 `_PIPELINE_STATE` / `_PIPELINE_CONFIG` / `_PIPELINE_STEP_MAP` 均解耦。纯内存计时器。

### 1.2 API 签名

```python
# ── 内部状态 ──
_timeout_timers: dict[str, dict] = {}
# key   = "{round_name}/{step_name}"
# value = {
#     "deadline": float,      # time.time() + timeout_minutes * 60
#     "notified": bool,       # 超时告警是否已发出（防重复）
#     "pm_escalated": bool,   # PM 协调是否已触发
#     "handler": callable,    # 可选：超时回调函数
# }

# ── 公共 API ──

def start_timer(round_name: str, step_name: str,
                timeout_minutes: int,
                on_timeout: callable = None) -> None:
    """
    启动 step 倒计时。
    先 clear_timer(round_name) 清旧计时 → 注册新计时。
    on_timeout 为可选回调（handler 传入超时触发函数）。
    """
    clear_timer(round_name)
    deadline = time.time() + timeout_minutes * 60
    _timeout_timers[f"{round_name}/{step_name}"] = {
        "deadline": deadline,
        "notified": False,
        "pm_escalated": False,
    }

def clear_timer(round_name: str) -> None:
    """清除指定 round 的所有计时器。（step 切换/管线关闭时调用）"""
    keys = [k for k in _timeout_timers if k.startswith(f"{round_name}/")]
    for k in keys:
        del _timeout_timers[k]

def get_remaining(round_name: str, step_name: str) -> float:
    """返回剩余秒数。未设置或已超时返回 0.0。"""
    timer = _timeout_timers.get(f"{round_name}/{step_name}")
    if not timer:
        return 0.0
    return max(0.0, timer["deadline"] - time.time())

def is_expired(round_name: str, step_name: str) -> bool:
    """检查是否已超时。"""
    return get_remaining(round_name, step_name) <= 0.0

def get_timer_info(round_name: str, step_name: str) -> dict | None:
    """返回计时器状态（供 pipeline_status 展示用）"""
    return _timeout_timers.get(f"{round_name}/{step_name}")
```

### 1.3 超时触发设计

**触发点**不在 `timeout_tracker.py` 内（不引入异步），而由 handler.py 的 `_pipeline_status` 路径和 `_watchdog_loop` 路径检查：

| 检查点 | 频次 | 逻辑 |
|:-------|:-----|:-----|
| `!_cmd_pipeline_status()` 展示时 | 每请求 | 调用 `timeout_tracker.get_remaining()` 展示剩余时间 |
| `_watchdog_loop()` 扫描（每 10 分钟） | 每 10 分钟 | 检查 `timeout_tracker.is_expired(round, step)` → 触发 PM 协调 |
| 退化开关关闭时 | — | watchdog 回退到旧行为（`PIPELINE_STEP_MAP` timeout_hours） |

**PM 协调触发函数（handler.py 新增）：**

```python
async def _trigger_timeout_escalation(round_name: str, step_name: str) -> str:
    """超时触发 → 工作室 @PM + _admin 频道告警"""
    step_cfg = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {}).get(step_name, {})
    timeout_mins = step_cfg.get("timeout_minutes", 15)
    remaining = timeout_tracker.get_remaining(round_name, step_name)
    over_by = max(0, int(timeout_mins * 60 - remaining))
    
    alert = (
        f"⏰ [超时告警] {round_name} {step_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏱ 预期完成时间: {timeout_mins}分钟\n"
        f"🕐 已超时: {over_by // 60}分{over_by % 60}秒\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请 PM 协调：是否跳过 / 换人 / 手动干预"
    )
    return alert
```

---

## 2. `_parse_frontmatter()` 解析策略评估

### 2.1 当前实现状态

函数已存在 (`handler.py` L960)，采用 **纯标准库解析**（无 pyyaml）：

| 子组件 | 行号 | 策略 |
|:-------|:----|:-----|
| `_parse_scalar(value)` | L939 | 处理引号剥离、boolean 解析（true/false/yes/no）、数值解析（int/float） |
| `_parse_frontmatter(content)` | L960 | `split('---')` → 取索引 1 的 frontmatter 段 → 逐行解析 |
| 缩进解析 | L968+ | 行首缩进决定层级嵌套，`:` 分割 key-value，`- ` 前缀为列表 |

### 2.2 已知局限 & 风险

| 局限 | 影响 | 缓解 |
|:-----|:-----|:-----|
| 不支持 YAML 多行 `|`/`>` block 标量 | WORK_PLAN frontmatter 不使用多行文本 | 当前 WORK_PLAN 格式兼容 |
| 不支持 `!!!str` 类型标签 | 不会出现 | 无影响 |
| 只抽取 `pipeline:` 顶层 key | 不解析其他 key | 需求设计如此 |
| 旧格式 WORK_PLAN（无 `---`） | 抛出 `NoFrontmatterError` | L966-967 捕获 → fallback 到 `_build_fallback_config` |

**结论：** 当前实现满足 R63 需求，**无需修改**。编码阶段仅需验证退化路径。

### 2.3 模板变量填充

`_build_pipeline_config()` (L1003) 支持 `${pipeline.xxx}` 模板替换：

```python
for ctx_key, ctx_value in list(context.items()):
    if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
        ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
        if ref_key in config:
            context[ctx_key] = str(config[ref_key])
```

**缺口：** `${steps.step2.output}` 这种跨 step 引用**未实现**。当前 WORK_PLAN 中 step3 的 `tech_plan_url: "${steps.step2.output}"` 不会被填充。但这不影响管线流转——step3 的上下文 URL 仍可从 requirements/plan 拼接获取。**建议将此模板能力标记为 P2 延后**，不影响本轮核心交付。

---

## 3. `_ROLE_AGENT_MAP` 构建策略

### 3.1 当前状态

```python
# handler.py L918 — 已存在但未被 _cmd_step_complete 调用
def _find_agents_by_role(role: str, member_ids: list[str],
                         cards: dict) -> list[str]:
    return [aid for aid in member_ids
            if role in _get_agent_card_roles(aid, cards)]
```

**问题：** `_cmd_step_complete` (L1629) 中查找下一角色 agent 使用 `auth.get_users().role`，所有 bot 的 role 均为 `member`，导致 F-16：角色匹配失败。

### 3.2 新设计

**新增全局 + 函数：**

```python
# handler.py 全局区（~L48, 与 _PIPELINE_CONFIG 并列）
_ROLE_AGENT_MAP: dict[str, list[str]] = {}
# key = pipeline_role (arch/dev/review/qa/admin)
# value = [agent_id_primary, agent_id_backup, ...]
```

**构建策略（优先级链）：**

```
① Agent Card pipeline_roles 明确绑定  →  _ROLE_AGENT_MAP[role] = [agent_id]
② 无 card 的角色                      →  回退 auth.get_users().role（当前行为）
③ 最终过滤                            →  只保留工作区成员
```

**核心函数：**

```python
def _refresh_role_agent_map() -> None:
    """
    从 Agent Card 的 pipeline_roles 重建 _ROLE_AGENT_MAP。
    在点名注册、!agent_role_map --refresh 时触发。
    """
    global _ROLE_AGENT_MAP
    cards = _load_agent_cards()
    _ROLE_AGENT_MAP = {}
    for aid, card in cards.items():
        roles = card.get("pipeline_roles", [])
        for role in roles:
            if role not in _ROLE_AGENT_MAP:
                _ROLE_AGENT_MAP[role] = []
            _ROLE_AGENT_MAP[role].append(aid)

def _get_agents_by_role(role: str,
                        workspace_members: list[str] = None) -> list[str]:
    """
    先查 _ROLE_AGENT_MAP，回退 auth.get_users().
    可选过滤 workspace_members.
    """
    agents = _ROLE_AGENT_MAP.get(role, [])
    if not agents:
        # Fallback to auth roles
        users = auth.get_users()
        agents = [aid for aid, u in users.items()
                  if u.get("role", "member") == role]
    if workspace_members:
        agents = [a for a in agents if a in workspace_members]
    return agents
```

### 3.3 点名注册逻辑

**触发点：** bot 在工作室回复点名（`!rollcall` / `!rollcall_role`）后 → 匹配回复内容 → 自动注册。

```python
# handler.py 消息处理路径中
async def _handle_rollcall_ack(sender_id: str, content: str,
                                ws_id: str) -> None:
    """处理点名回复 → 自动注册/更新 Agent Card"""
    cards = _load_agent_cards()
    aid = sender_id
    
    if aid in cards:
        # 已有 card → 更新在线状态
        cards[aid]["last_online"] = time.time()
        cards[aid]["status"] = "online"
    else:
        # 无 card → 智能注册
        users = auth.get_users()
        u = users.get(aid, {})
        cards[aid] = {
            "name": u.get("name", aid[:12]),
            "display_name": u.get("name", aid[:12]),
            "pipeline_roles": [u.get("role", "member")],
            "skills": [],
            "status": "online",
            "registered_at": time.time(),
            "last_online": time.time(),
            "trigger_preference": {
                "mode": "mention",
                "mention_keyword": u.get("name", aid[:12]),
                "ack_timeout_sec": 60,
            },
            "capabilities": {
                "platforms": ["ws-bridge"],
                "can_code": True,
                "can_review": True,
                "can_deploy": False,
            },
        }
    _save_agent_cards(cards)
    _refresh_role_agent_map()
```

### 3.4 Step 路由改造

```python
# _cmd_step_complete 中查找下一角色 agent（替换现有 auth.get_users().role 查找）
# 在 L1703-1708 step_config 解析之后
next_role = step_config[next_step].get("role", "")
next_agents = _get_agents_by_role(next_role, ws_obj.members)
if not next_agents:
    return f"❌ 工作区中未找到角色为 {next_role} 的成员(F-16)"
```

### 3.5 管理命令

| 命令 | 功能 |
|:-----|:------|
| `!agent_role_map` | 遍历 `_ROLE_AGENT_MAP` + 补全，输出格式化映射表 |
| `!agent_role_map --refresh` | 调用 `_refresh_role_agent_map()` + 同上输出 |
| `!agent_card register <agent_id>` | 强制注册（从 auth 取信息写入 card） |
| `!agent_card auto-register` | 扫描所有在线 agent 补全缺失 card |

---

## 4. ACK 状态机设计

### 4.1 数据结构

```python
# handler.py 全局区
_step_ack_states: dict[str, dict] = {}
# key = "{round_name}/{step_name}"
# value = {
#     "state": str,        # SENT | DELIVERED | ACKNOWLEDGED | IN_PROGRESS | FAILED
#     "agent_id": str,     # 目标 agent
#     "sent_at": float,    # 发送时间戳
#     "deadline": float,   # ACK 超时时间戳 (sent_at + ACK_TIMEOUT_SEC)
#     "delivery_sent": int, # delivery ack 中 sent 计数
# }
```

### 4.2 状态机转换图

```
                    ┌─────────────────────────────────────────────┐
                    │            _assign_step_agent()             │
                    │                 ↓                           │
                    │             SENT ────────── 超时 30s ──→ FAILED
                    │               │                               │
                    │               │ delivery ack {sent: 0}        │
                    │               ↓                               │
                    │          FAILED (离线, 切换备用)              │
                    │               │                               │
                    │               │ delivery ack {sent: N, N>0}   │
                    │               ↓                               │
                    │          DELIVERED                            │
                    │               │                               │
                    │               │ bot 回复任何消息               │
                    │               ↓                               │
                    │       ACKNOWLEDGED                            │
                    │               │                               │
                    │               │ 回复含「收到」「好的」等       │
                    │               ↓                               │
                    │       IN_PROGRESS                             │
                    └─────────────────────────────────────────────┘
```

### 4.3 ACK 超时

```python
ACK_TIMEOUT_SEC = 30  # 从 SENT 到 FAILED 的超时秒数

async def _assign_step_agent(round_name: str, step_name: str,
                              target_agent_id: str) -> str:
    """派发 step 任务给目标 agent → 启动 ACK 状态机"""
    ack_key = f"{round_name}/{step_name}"
    _step_ack_states[ack_key] = {
        "state": "SENT",
        "agent_id": target_agent_id,
        "sent_at": time.time(),
        "deadline": time.time() + ACK_TIMEOUT_SEC,
        "delivery_sent": 0,
    }
    # 启动异步超时任务
    asyncio.create_task(_ack_timeout_task(ack_key))
    return ack_key

async def _ack_timeout_task(ack_key: str) -> None:
    """30 秒 ACK 超时检测"""
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    state = _step_ack_states.get(ack_key, {})
    if state.get("state") in ("SENT", "DELIVERED"):
        state["state"] = "FAILED"
        # 触发 PM 协调
        await _trigger_ack_escalation(ack_key, state)
```

### 4.4 Delivery ACK 解析

在 `handler.py` 的 WebSocket 消息处理入口中，检测 `"type": "ack"` 消息：

```python
# 在 handler() 入口中（L~220-250 区域）
if isinstance(msg, dict) and msg.get("type") == "ack":
    delivery = msg.get("delivery", {})
    if isinstance(delivery, dict):
        total = delivery.get("total", 0)
        sent = delivery.get("sent", 0)
        # 更新所有匹配的 ACK 状态
        for ack_key, ack_state in _step_ack_states.items():
            if ack_state["state"] == "SENT":
                if sent == 0:
                    ack_state["state"] = "FAILED"
                    ack_state["delivery_sent"] = 0
                else:
                    ack_state["state"] = "DELIVERED"
                    ack_state["delivery_sent"] = sent
```

### 4.5 Bot ACK 检测

在消息处理路径中，检测目标 agent 在工作室的回复：

```python
# 在消息路由路径中（方向 A7/C5 附近的 ACK 处理）
ack_content = content.strip()
ack_keywords = ["收到", "好的", "在", "到", "接", "OK", "ok", "开始"]
is_ack = any(kw in ack_content for kw in ack_keywords)

for ack_key, ack_state in _step_ack_states.items():
    if ack_state.get("agent_id") == sender_id and ack_state["state"] in ("SENT", "DELIVERED"):
        ack_state["state"] = "ACKNOWLEDGED" if not is_ack else "IN_PROGRESS"
```

### 4.6 PM 协调触发

```python
async def _trigger_ack_escalation(ack_key: str, state: dict) -> str:
    """ACK 超时 → PM 协调"""
    round_step = ack_key.split("/", 1)
    display_name = _get_agent_display(state.get("agent_id", ""))
    alert = (
        f"🕐 [ACK 超时] {round_step[0]} {round_step[1]}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 目标: {display_name}\n"
        f"📨 状态: {state.get('state', 'UNKNOWN')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请 PM 协调：等待 / 换备用 / 手动驱动 / 跳过"
    )
    return alert
```

### 4.7 状态展示

在 `_cmd_pipeline_status` 中集成：

```
📊 R63 管线状态
  当前 Step: step2 (技术方案)
  ⏱ 剩余: 17分 / 20分钟
  🎯 目标: arch
  📨 派发: ✅ DELIVERED → 等待 ACK (已过 8秒)
```

---

## 5. 退化开关设计

### 5.1 开关定义（config.py）

```python
# ── R63: 新能力退化开关 ──
_ENABLE_R63_TIMEOUT: bool = True    # True=新倒计时, False=退回 watchdog
_ENABLE_R63_AGENT_MAP: bool = True  # True=映射表路由, False=旧 auth lookup
_ENABLE_R63_ACK: bool = True        # True=ACK 状态机, False=单向通知
```

**默认值：全开（True）**。通过环境变量覆盖，每个开关独立生效：

```python
import os
_ENABLE_R63_TIMEOUT = os.environ.get("R63_ENABLE_TIMEOUT", "1") == "1"
_ENABLE_R63_AGENT_MAP = os.environ.get("R63_ENABLE_AGENT_MAP", "1") == "1"
_ENABLE_R63_ACK = os.environ.get("R63_ENABLE_ACK", "1") == "1"
```

### 5.2 各开关消费点

| 开关 | handler.py 守卫点 | 关闭后行为 |
|:-----|:-----------------|:-----------|
| `_ENABLE_R63_TIMEOUT` | `_cmd_pipeline_status` 倒计时展示 / `_watchdog_loop` 超时检查 | 不展示剩余时间，watchdog 用旧 timeout_hours |
| `_ENABLE_R63_AGENT_MAP` | `_cmd_step_complete` / `_cmd_step_handoff` 角色查找 | 回退 `auth.get_users().role` |
| `_ENABLE_R63_ACK` | `_assign_step_agent` / `_ack_timeout_task` | 不注册 ACK 状态机，用旧单向通知 |

### 5.3 退化矩阵验证

| 开关组合 | 预期行为 |
|:---------|:---------|
| 全关（False/False/False） | 管线行为与 R61 一致（旧 watchdog + auth lookup + 单向通知） |
| 仅 TIMEOUT 开 | 倒计时工作，路由走旧路径，ACK 走旧通知 |
| 仅 AGENT_MAP 开 | 映射表路由，倒计时走旧 watchdog，ACK 走旧通知 |
| 全开（True/True/True） | 完整 R63 新能力 |

---

## 6. Direction E 顺手修复 — 检查结果

### 6.1 E1: `_send_to_agent` from_name 覆盖检查

经代码审计：

| 场景 | 当前 from_name | 结论 |
|:-----|:--------------|:-----|
| 管线启动 kickoff (L1521) | `pm_name` (config.PIPELINE_PM_NAME) | ✅ 已修复 |
| rollcall 点名 (L1549) | 使用 `_cmd_rollcall_next` → 内部用 PM name | ✅ |
| Step 交接通知 | `_cmd_step_complete` 中 `_persist_broadcast(ws_id, pm_name, ...)` | ✅ |
| `_send_to_agent` 直接调用 | 需 grep 确认 | ⚠️ 编码阶段验证 |

### 6.2 E2: F-16 修复

由 Direction B 的 `_get_agents_by_role()` + `_ROLE_AGENT_MAP` 解决。`_cmd_step_complete` 中替换 `auth.get_users().role` 查找为映射表查找。

### 6.3 E3: `!step_handoff` 状态丢失修复

由 R62 的 `_PIPELINE_CONFIG` config/state 分离解决——state 丢失后 config 仍可读 status。

### 6.4 E4: 超时精确度提升

以 Direction A 的精确倒计时替代 10 分钟扫描。

---

## 7. 编码阶段实施顺序

基于代码现状（R62 基础设施已就位），重排 Phase：

| Phase | 包含 | 预计行数 | 依赖 |
|:------|:-----|:--------|:-----|
| **Phase 0** | 验证 R62 基准（✅-23~✅-30） | ~0 行 | 依赖 dev 容器 |  
| **Phase 1** | `server/timeout_tracker.py` 新建 | ~80 行 | 无 |
| **Phase 2** | 倒计时集成：status 展示 + 超时触发 + step 切换清理 | ~40 行 | Phase 1 |
| **Phase 3** | `_ROLE_AGENT_MAP` + 点名注册 + 命令增强 | ~50 行 | Phase 2 (无代码依赖) |
| **Phase 4** | ACK 状态机 + 派发集成 | ~55 行 | Phase 3 (可并行) |
| **Phase 5** | 退化开关 + config.py + 消费点 + E 修复 | ~20 行 | Phase 1-4 |
| **合计** | | **~245 行净增** | |

**并行说明：** Phase 3 和 Phase 4 之间无代码依赖，可并行编码或在同一批次中连续完成。

---

## 8. 关键风险 & 应对

| 风险 | 影响 | 应对 |
|:-----|:-----|:-----|
| ACK 状态机异步任务泄漏 | 内存泄漏、重复告警 | `_ack_timeout_task` 内部检查 state 是否已变更，状态机只工作一次 |
| watchdog 与新倒计时并行告警 | 双重告警 | watchdog 检查 `timeout_tracker.is_expired()` 已超时才触发，新倒计时先到先触发 |
| 退化开关全开 → 首次部署异常 | 管线行为变化 | Phase 5 最后部署，先逐 Phase 验证再开全量 |
| R62 frontmatter 解析器在生产环境抛异常 | 管线启动失败 | `_parse_frontmatter` 捕获一切异常 → fallback（L1428-1443 已实现） |

---

## 9. 验收映射表

| 验收项 | 方向 | 技术方案覆盖 |
|:------:|:----|:-------------|
| ✅-1 ~ ✅-8 | 方向 A | §1 timeout_tracker.py + §2 frontmatter 评估 |
| ✅-9 ~ ✅-14 | 方向 B | §3 Agent Card + 角色映射 |
| ✅-15 ~ ✅-19 | 方向 C | §4 ACK 状态机 |
| ✅-20 ~ ✅-22 | 方向 D | §5 退化开关 |
| ✅-23 ~ ✅-30 | 方向 A5 | §0 前置发现（R62 已就位） |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-01 | 初始版本 |
