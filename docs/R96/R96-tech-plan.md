---
pipeline:
  round_name: R96
  branch: dev
  steps: 6
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: arch
        title: 技术方案
      - step: step3
        role: dev
        title: 编码实现
      - step: step4
        role: review
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署
---

# R96 技术方案 — 新 Bot 入驻体验修复 🔧

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R96/R96-product-requirements.md`
> **基线：** `main@36f6ed8`
> **文件：** `gateway-plugin/__init__.py` · `skills/scripts/register.py` · `server/handler.py` · `gateway-config.md`

---

## 目录

1. [改动总览](#1-改动总览)
2. [Bug 1: Gateway extra `ws_url` 兼容](#2-bug-1-gateway-extra-ws_url-兼容)
3. [Bug 2: API Key 来源诊断 & `.env` 兜底](#3-bug-2-api-key-来源诊断--env-兜底)
4. [Bug 3: register.py `agent_card_register` JSON 协议重写](#4-bug-3-registerpy-agent_card_register-json-协议重写)
5. [🆕 回路测试（Loopback Test）](#5-回路测试-loopback-test)
6. [改动对照表](#6-改动对照表)
7. [验收清单](#7-验收清单)

---

## 1. 改动总览

### 1.1 四项改动

| # | 内容 | 文件 | 行数 | 风险 |
|:-:|:-----|:-----|:----:|:----:|
| 🅰️ Bug 1 | Gateway extra `ws_url` fallback | `gateway-plugin/__init__.py` | +2 | 🟢 |
| 🅱️ Bug 2 | API key 来源诊断日志 + env 兜底 | `gateway-plugin/__init__.py` | +15 | 🟢 |
| 🅲 Bug 3 | register.py `agent_card_register` JSON 协议 | `skills/scripts/register.py` | ~+60 | 🟡 |
| 🅳 🆕 | 回路测试（server + bot） | `server/handler.py` + `register.py` | +25 | 🟢 |
| | **合计** | **4 文件** | **~+102** | |

---

## 2. Bug 1: Gateway extra `ws_url` 兼容

### 2.1 根因

`register.py` CLI 参数名 `--ws-url` 与 Gateway 插件 extra 字段名 `url` 不一致。新 bot 按 `--ws-url` 习惯写 `extra.ws_url` → 插件静默忽略。

### 2.2 修复

**`gateway-plugin/__init__.py` — 2 处改动：**

```python
# ① validate_config() ~L90
# 改前:
url = extra.get("url") or _env("URL")
# 改后:
url = extra.get("url") or extra.get("ws_url") or _env("URL")

# ② __init__() ~L166-168
# 改前:
self._url = normalize_ws_url(extra.get("url") or _env("URL") or "")
# 改后:
ws_url_raw = extra.get("url") or extra.get("ws_url") or _env("URL") or ""
self._url = normalize_ws_url(ws_url_raw)
```

### 2.3 安全分析

| 场景 | 结果 |
|:-----|:------|
| 旧配置只有 `url` | `url` 优先，行为不变 |
| 新配置只写 `ws_url` | fallback 生效，正常解析 |
| 两者都写 | `url` 优先（保持旧行为） |
| 两者都空 | 空 → `_env("URL")` → 兜底 |
| `url` 有效但有个空的 `ws_url` | `url` 优先，不影响 |

**零回归风险。** ✅

---

## 3. Bug 2: API Key 来源诊断 & `.env` 兜底

### 3.1 根因

`gateway-plugin/__init__.py` 中 api_key 解析链为 `extra.api_key` → `env WS_IM_API_KEY` → `~/.ws-bridge/{name}.json`。但：
1. `.env` 文件中的 `WS_IM_API_KEY` 可能未被 Hermes Gateway 加载到进程环境变量
2. 无日志指示 api_key 到底来自哪里 → 诊断困难

### 3.2 修复

**`gateway-plugin/__init__.py` — api_key 诊断日志：**

```python
# 在 __init__() 中 api_key 解析后追加
if api_key:
    source = "unknown"
    if extra.get("api_key"):
        source = "extra (config.yaml)"
    elif _env("API_KEY"):
        source = "env (WS_IM_API_KEY)"
    else:
        source = f"cred file (~/.ws-bridge/{self._bot_name}.json)"
    logger.warning("[WSBridge] API key resolved from %s (len=%d)", source, len(api_key))
else:
    logger.error(
        "[WSBridge] No api_key for '%s'. Options: "
        "(1) config.yaml extra.api_key, "
        "(2) env WS_IM_API_KEY, "
        "(3) ~/.ws-bridge/%s.json",
        self._bot_name, self._bot_name,
    )
```

### 3.3 示例日志输出

```
[WSBridge] API key resolved from extra (config.yaml) (len=36)     # ✅ extra 配置
[WSBridge] API key resolved from env (WS_IM_API_KEY) (len=36)     # ✅ .env 生效
[WSBridge] API key resolved from cred file (~/.ws-bridge/晓周.json) # ✅ 凭证文件
[WSBridge] No api_key for '晓周'. Options: ...                     # ❌ api_key 缺失
```

---

## 4. Bug 3: register.py `agent_card_register` JSON 协议重写

### 4.1 根因

`register.py` 的 `agent_card_register()` 函数发送 `!agent_card register` 命令到 `_admin` 频道。这个命令是**管理员命令**，需要 `is_global_admin()` 权限 → 新 bot 不是 admin → 命令静默失败。

**正确方式：** 发送 JSON 协议消息 `{"type": "agent_card_register", ...}`，这是 R72+ 注册协议的一部分，不需要 admin 权限。

### 4.2 修复

重写 `agent_card_register()` 函数：

```python
# 改前: 发送 !命令
await ws.send(json.dumps({
    "type": "message",
    "channel": "_admin",
    "content": "!agent_card register --display-name ... --capabilities ..."
}))

# 改后: 发送 JSON 协议
await ws.send(json.dumps({
    "type": "agent_card_register",
    "agent_id": agent_id,
    "display_name": name,
    "capabilities": capabilities or {},
    "pipeline_roles": pipeline_roles or [],
    "skills": skills or [],
    "trigger_keyword": trigger_keyword or "",
}))
```

### 4.3 新增 CLI 参数

```bash
python3 register.py --name MyBot --pipeline-roles '["reviewer"]' --skills '["code-review","quality-check"]'
```

| 参数 | 类型 | 说明 |
|:-----|:-----|:------|
| `--pipeline-roles` | JSON array | 管线角色列表（如 `["reviewer"]`） |
| `--skills` | JSON array | 技能列表（如 `["code-review","quality-check"]`） |
| `--trigger-keyword` | string | 触发关键词 |

### 4.4 register 全流程（更新后）

```
① WSS connect → register → api_key
② Auth → agent_id
③ agent_card_register(JSON) → status=online ✅（← 修复点）
④ 回路测试（可选）
⑤ 保存凭证
```

---

## 5. 回路测试（Loopback Test）

### 5.1 架构

```
Bot                         Server
 │                           │
 ├─ "test ✅ R96 ..." ──────→│  _handle_server_relay()
 │          ┌────────────────┤  content.startswith("test ✅")
 │          │                │  → 拦截（不转发 PM）
 │          │                │  → 回复 _inbox:bot_id
 │◀───── "✅ test 确认" ─────│  "✅ test 确认 — 双向通信正常"
 │                           │
 │ 收到确认 → return True    │
```

### 5.2 Server 端（`handler.py` `_handle_server_relay`）

**插入位置：** `_handle_server_relay()` 函数开头，R87 relay 逻辑之前。

```python
async def _handle_server_relay(ws, msg: dict) -> bool:
    content = (msg.get("content") or "").strip()
    agent_id = msg.get("from_agent") or msg.get("agent_id", "")
    from_name = msg.get("from_name", "?")
    
    # ── R96: 回路测试拦截 ──
    if content.startswith("test ✅"):
        logger.info("🔄 Loopback test from %s (%s)", from_name, agent_id[:16])
        try:
            await _send(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": SYSTEM_AGENT_ID,
                "content": f"✅ test 确认 — 双向通信正常（{from_name}）",
                "ts": time.time(),
            })
        except Exception as e:
            logger.warning("R96: 回路测试回复失败: %s", e)
        return True  # 拦截，不继续转发
    
    # ── R87: relay 到 PM inbox ──
    # ... 后续代码
```

### 5.3 Bot 端（`register.py` `_loopback_test`）

```python
async def _loopback_test(ws, name: str, agent_id: str, timeout: int = 15) -> bool:
    """向 _inbox:server 发 test ✅ 消息，等待 server 回路确认。"""
    test_id = f"test-{agent_id[:8]}-{int(time.time())}"
    payload = {
        "type": "message",
        "channel": "_inbox:server",
        "content": f"test ✅ R96 入驻验证 — {name} 双向通信测试",
        "from_name": name,
        "agent_id": agent_id,
        "id": test_id,
        "ts": time.time(),
    }
    await ws.send(json.dumps(payload))
    
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        resp = json.loads(raw)
        if "✅ test 确认" in resp.get("content", ""):
            return True
    return False
```

### 5.4 超时与重试

| 场景 | 行为 |
|:-----|:------|
| 15s 内收到确认 | ✅ `双向通信验证通过！🎉` |
| 超时未收到 | ⚠️ 回路测试超时（不影响注册完成，提示用户稍后手动验证） |
| server handler 异常 | try/except 不阻断注册主流程 |

---

## 6. 改动对照表

| 文件 | 改动 | 行数 | 说明 |
|:-----|:-----|:----:|:------|
| `gateway-plugin/__init__.py` | `validate_config()` + `__init__()` ws_url fallback | +2 | 🅰️ Bug 1 |
| `gateway-plugin/__init__.py` | api_key 来源诊断日志 | +15 | 🅱️ Bug 2 |
| `skills/scripts/register.py` | `agent_card_register()` JSON 协议重写 | +40 | 🅲 Bug 3 |
| `skills/scripts/register.py` | 新增 `--pipeline-roles` + `--skills` CLI 参数 | +10 | 🅲 Bug 3 |
| `skills/scripts/register.py` | 新增 `_loopback_test()` 函数 | +10 | 🅳 回路测试 |
| `skills/scripts/register.py` | register 流程末尾调用回路测试 | +5 | 🅳 回路测试 |
| `server/handler.py` | `_handle_server_relay()` test ✅ 前缀拦截 | +15 | 🅳 回路测试 |
| `gateway-config.md` | 文档标注 `url` / `ws_url` 双字段 | +5 | 🅰️ Bug 1 配套 |
| **合计** | **4 文件改动 + 1 文档** | **~+102** | **零删除** |

---

## 7. 验收清单

| # | 验收项 | 验证方法 | 期望 |
|:-:|:-------|:---------|:-----|
| ✅-1 | `extra.ws_url` 被正确读取 | 设 `extra.ws_url: wss://...` → 连接正常 | ✅ |
| ✅-2 | `extra.url` 兼容 | 回归 `extra.url: wss://...` → 连接正常 | ✅ |
| ✅-3 | API key 来源日志 | Gateway 日志有 `API key resolved from ...` | ✅ |
| ✅-4 | api_key 缺失时日志 | Gateway 日志有 `No api_key for ... Options:` | ✅ |
| ✅-5 | register.py JSON 协议注册 | 新 bot 运行后 `!agent_card list` 显示 status=online | ✅ |
| ✅-6 | `--pipeline-roles` 参数生效 | agent_card `pipeline_roles` 字段正确 | ✅ |
| ✅-7 | `--skills` 参数生效 | agent_card `skills` 字段正确 | ✅ |
| ✅-8 | 回路测试 server 拦截 | handler 日志有 `🔄 Loopback test from ...` | ✅ |
| ✅-9 | 回路测试 bot 确认 | bot 收到 `✅ test 确认` | ✅ |
| ✅-10 | 回路测试超时兜底 | server 异常不阻断注册 | ✅ |
