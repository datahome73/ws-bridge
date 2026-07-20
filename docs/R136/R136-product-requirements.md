# R136 产品需求 — 纯提取轮：连接管理 + 看门狗 + ACK 状态机

> **起草人：** 🧐 PM
> **状态：** 📝 草稿
> **版本：** v1.0
> **日期：** 2026-07-20
> **依据文档：** `server/ws_server/README.md` §9 重构清单

---

## 0. R136 定位

```
R135（已上线）— 死代码清理：handle_broadcast + 频道体系精简 (-600行)
R136（本轮）    — 纯提取轮：连接管理/看门狗/ACK状态机/Git调度/超时扫描 独立成模块
R137（下轮）    — 行为拆分：##命令迁入pipeline_engine + 规则注册统一
```

R136 是**零语义改动轮**——只搬文件，不改逻辑。每块提取后独立测试，确保行为不变。

---

## 1. 背景与目标

### 1.1 现状

R135 之后 `main.py` 从 3,706 行降至 **3,092 行**。虽然死代码清理了，但独立模块仍然嵌入在 main.py 中：

| 模块 | 行数 | 当前状态 |
|---|---|---|
| 连接管理（auth/register/`_connections`/`_send`） | ~200 | 嵌在 main.py L37-L366 |
| 看门狗（watchdog 循环 + 告警） | ~300 | 嵌在 main.py L429-L1152 |
| ACK 状态机 | ~50 | 嵌在 main.py L883-L1008 |
| 超时扫描 | ~60 | 嵌在 main.py L489-L616 |
| Git 同步调度层 | ~30 | 嵌在 main.py L443-L487 |
| **合计可提取** | **~640** | |

### 1.2 目标

将 ~640 行零语义提取到 5 个独立模块中，`main.py` 从 3,092 → **~2,450 行**。
每个模块：
- 导入后功能与原位置完全一致
- 不改变任何函数签名或行为
- 提取后可独立做单元测试

### 1.3 范围界定

| 范围 | 包含 | 不包含 |
|---|---|---|
| 连接管理 | auth/register/`_connections`/`_send`/`_send_to_agent`/`handler()` 连接粘合 | 连接池化（`dict→class` 重构） |
| 看门狗 | watchdog 循环/告警/escalation | 死代码清理（R135 已做） |
| ACK 状态机 | 超时检测/状态更新/展示 | 非核心清理（R135 已删告警通知） |
| 超时扫描 | R122 超时扫描定时器 | 扫描逻辑本身 |
| Git 同步调度 | ensure/start 调度层 | pipeline_sync.py 检测逻辑本身 |

---

## 2. 功能需求

### EXT-1（提取 A）：连接管理 → `connection_manager.py`

**范围（~200 行）：**

```
main.py L37-L40     _connections / _send_stats / engine 声明
main.py L68-L70     get_connections()
main.py L130-L149   _force_disconnect_revoked_agent() ×2（覆盖同名的重载）
main.py L140-L148   _send() — 统一发送器
main.py L160-L207   handle_auth() — api_key 认证
main.py L189-L197   _update_agent_online_status()
main.py L204-L208   _find_agent_by_name()
main.py L212-L327   handle_register() — 新 bot 注册
main.py L270-L327   handle_agent_card_register() — Agent Card 自主注册
main.py L1495       _is_valid_agent_id()
main.py L1500-L1540 _send_to_agent() — 单播网关
```

**提取后接口：**

```python
from .connection_manager import (
    init_connections,       # 模块级 _connections 初始化
    get_connections,        # 读接口
    _send,                  # 发送
    _send_to_agent,         # 单播
    handle_auth,            # 认证
    handle_register,        # 注册
    _force_disconnect_revoked_agent,
    _is_valid_agent_id,
)
```

**依赖：** `shared.protocol`、`server.common.auth`、`server.common.config`、`server.common.persistence`、`agent_card`、`state`
**其他模块的引用：**

| 引用者 | 引用内容 |
|---|---|
| `__main__.py` | `handle_auth`, `handle_register`, `_connections` |
| `scenario_matcher.py` | `_send_to_agent` (通过 engine 注入) |
| `pipeline_engine.py` | `_send_to_agent` (通过构造注入) |
| `scenario_matcher` 回调 (main.py 底部) | `_send`, `_send_to_agent` |

### EXT-2（提取 B）：看门狗 → `watchdog.py`

**范围（~300 行）：**

```
main.py L429        _ensure_watchdog()
main.py L739-L747   _watchdog_loop()
main.py L749-L815   _watchdog_scan()
main.py L817-L827   _get_step_timeout()
main.py L829-L880   _trigger_timeout_escalation()
main.py L1038-L1055 _check_watchdog_alert()
main.py L1058-L1065 _clear_watchdog_alert()
main.py L1067-L1072 _elapsed_hours_display()
main.py L1074-L1130 _send_watchdog_alert()
main.py L1134-L1150 _watchdog_rerollcall()
main.py L1152-L1170 _send_clear_alert()
```

**提取后接口：**

```python
from .watchdog import (
    ensure_watchdog,        # _ensure_watchdog
    format_watchdog_alert,  # 告警格式化
    check_alert_dedup,      # _check_watchdog_alert / _clear
)
```

**注意：** `_watchdog_scan()` 中仍引用 `state._PIPELINE_STATE` 等变量，需通过 `pipeline_context.py` 的接口读取。看门狗当前还是读模块级 state 字典，提取时保持同样的引用方式。

### EXT-3（提取 C）：ACK 状态机 → `ack_machine.py`

**范围（~50 行）：**

```
main.py L883-L901   _ack_timeout_task()      — 30秒超时检测
main.py L1008-L1035 _format_ack_status()     — ACK 状态格式化
main.py L1429-L1442 _task_ack_timeout()      — 任务 ACK 超时
main.py L1444-L1482 _channel_ack_timeout()   — 频道 ACK 超时
main.py L1484-L1493 _resolve_ws_by_ack_task_id()
```

**依赖：** `state`、`config`

### EXT-4（提取 D）：超时扫描 → `pipeline_timeout.py`

**范围（~60 行）：**

```
main.py L489-L506   _ensure_timeout_scanner()
main.py L508-L516   _start_timeout_scan_loop()
main.py L518-L614   _pipeline_timeout_scan()
```

**依赖：** `pipeline_context`、`config`、`_send_to_agent`(回调)

### EXT-5（提取 E）：Git 同步调度 → `git_sync_scheduler.py`

**范围（~30 行）：**

```
main.py L443-L451   _ensure_git_scan()
main.py L453-L461   _start_git_sync_loop()
main.py L463-L487   _pipeline_git_sync_scan()
```

**说明：** 这是 pipeline_sync.py 的调度层（启动/循环/遍历），不是检测逻辑本身（已在 pipeline_sync.py 中）。

---

## 3. 提取原则

### 3.1 提取方式

```
原位置: 
  def _some_function(...):
      ...

提取后 connection_manager.py:
  def _some_function(...):
      ...  # 完全相同的代码

原位置 main.py:
  from .connection_manager import _some_function
  # 保留原函数名，方便引用者无感
```

### 3.2 不做的

| 事项 | 原因 |
|---|---|
| 函数重命名 | 保持 `_` 前缀和原名，减少 diff |
| 参数签名变更 | 零语义改动，动签名就算语义变更 |
| 合并同类函数 | 纯搬运，不做重构 |
| 并发安全改造 | `_connections` 仍用原生 dict |
| 全局变量消除 | `state._*` 引用保持原样 |

### 3.3 验证方法

每提取一个模块后：

```bash
python3 -c "from server.ws_server import main"          # 无 ImportError
python3 -c "from server.ws_server.connection_manager import handle_auth, _send"  # 新模块可导入
```

---

## 4. 验收标准

| # | 验收项 | 类型 | 状态 |
|:-:|:-------|:----:|:----:|
| EXT-1 | `connection_manager.py` 创建，`main.py` import 替换后 import 正常 | P0 | ⬜ |
| EXT-2 | `watchdog.py` 创建，`main.py` import 替换后 import 正常 | P0 | ⬜ |
| EXT-3 | `ack_machine.py` 创建，`main.py` import 替换后 import 正常 | P0 | ⬜ |
| EXT-4 | `pipeline_timeout.py` 创建，`main.py` import 替换后 import 正常 | P0 | ⬜ |
| EXT-5 | `git_sync_scheduler.py` 创建，`main.py` import 替换后 import 正常 | P0 | ⬜ |
| R136-1 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | ⬜ |
| R136-2 | `##status` 查询管线状态正常 | P0 | ⬜ |
| R136-3 | `##start##R136` 管线启动 + 派活正常 | P0 | ⬜ |
| R136-4 | 看门狗首次消息后启动（_ensure_watchdog 惰性）| P0 | ⬜ |
| R136-5 | Git sync 扫描正常启动 | P1 | ⬜ |
| R136-6 | 超时扫描正常启动 | P1 | ⬜ |
| R136-7 | `_inbox:{agent_id}` 单播投递正常 | P0 | ⬜ |
| R136-8 | `_inbox:server` 规则表路由正常 | P0 | ⬜ |

---

## 5. 方向决定

| 决定事项 | 选择 | 说明 |
|:--------|:----|:-----|
| 实现范围 | 仅服务端 | `server/ws_server/` |
| 提取顺序 | 连接管理 → 看门狗 → ACK → 超时扫描 → Git | 按依赖和风险排序 |
| 不做事项 | `##` 命令迁移到 engine | 留 R137 |
| 不做事项 | `_connections` 池化 | 留 R138 |
| 不做事项 | `_send_to_agent` 统一网关 | 留 R138 |
| 不做事项 | 规则注册回调统一 | 留 R137 |

---

## 6. 开放问题

| # | 问题 | 建议方向 | 决策者 |
|:-:|:-----|:--------|:------|
| 1 | 提取后各模块间循环依赖风险 | main.py 作为 hub 导入各模块，各模块不互相导入 | 项目负责人 |

---

> **审核记录：**
> - v1.0 提交审核：[@2026-07-20]
> - 项目负责人审核意见：
> - 结论：⬜ 待审核
