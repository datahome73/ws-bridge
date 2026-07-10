# R96 技术方案 — 新 Bot 入驻体验修复 🔧

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R96/R96-product-requirements.md` v1.0
> **改动文件：** `gateway-plugin/__init__.py` · `handler.py` · `register.py` · `gateway-config.md`
> **净行数：** ~+110 行（纯新增/修改，零删除）

---

## 改动总览

| # | 类别 | 文件 | 行数 | 优先级 |
|:-:|:-----|:-----|:----:|:------:|
| 🅰️ | Gateway 字段兼容 | `gateway-plugin/__init__.py` | ~+20 | 🔴 P0 |
| 🅱️ | api_key 来源诊断 | `gateway-plugin/__init__.py` | ~+15 | 🟡 P2 |
| 🅲 | register.py 协议修复 | `register.py` | ~+60 | 🔴 P0 |
| 🅳 | 回路测试 | `handler.py` + `register.py` | ~+25 | 🟢 P3 |
| 🅴 | 配置文档修正 | `gateway-config.md` | ~+30 | 🟡 P2 |

---

## 🅰️ Gateway 字段兼容 (__init__.py)

### A-1 `ws_url` fallback for `url`

**当前代码：**
```python
# __init__.py L166-168
self._url = normalize_ws_url(
    extra.get("url") or _env("URL") or ""
)
```

**改为：**
```python
ws_url_raw = extra.get("url") or extra.get("ws_url") or _env("URL") or ""
self._url = normalize_ws_url(ws_url_raw)
```

**同步修改 `validate_config()` (L90)：**
```python
# 改前
url = extra.get("url") or _env("URL")
# 改后
url = extra.get("url") or extra.get("ws_url") or _env("URL")
```

### A-2 其他字段静默兼容

| 标准字段 | Fallback | 位置 |
|:---------|:---------|:-----|
| `api_key` | `apikey` / `api-key` | `__init__.py` L179 |
| `bot_name` | `name` / `display_name` | `__init__.py` L170 |

```python
# 改前
self._bot_name = extra.get("bot_name") or _env("BOT_NAME") or ""
# 改后
self._bot_name = (
    extra.get("bot_name")
    or extra.get("name")
    or extra.get("display_name")
    or _env("BOT_NAME")
    or ""
)

# api_key
api_key = extra.get("api_key") or extra.get("apikey") or extra.get("api-key") or _env("API_KEY") or ""
```

---

## 🅱️ api_key 来源诊断日志 (__init__.py)

在 `__init__.py` 中 api_key 解析完毕后增加诊断日志：

```python
if api_key:
    source = "unknown"
    if extra.get("api_key") or extra.get("apikey") or extra.get("api-key"):
        source = "extra (config.yaml)"
    elif _env("API_KEY"):
        source = "env (WS_IM_API_KEY)"
    else:
        source = f"cred file (~/.ws-bridge/{self._bot_name}.json)"
    logger.warning("[WSBridge] API key resolved from %s (len=%d)", source, len(api_key))
else:
    logger.error("[WSBridge] No api_key for '%s'. Options: (1) config.yaml extra.api_key, (2) env WS_IM_API_KEY, (3) ~/.ws-bridge/%s.json", self._bot_name, self._bot_name)
```

---

## 🅲 register.py 协议修复 (核心修复)

### C-1 `agent_card_register()` 重写

**将命令路径 `type="message"` + `!agent_card register` 改为 JSON 协议 `type="agent_card_register"`：**

```python
# register.py → agent_card_register()
# ❌ 旧路径（静默失败）
await ws.send(json.dumps({
    "type": "message",
    "channel": "_admin",
    "content": "!agent_card register --display-name ...",
}))

# ✅ 新路径（正确 JSON 协议）
async with websockets.connect(ws_url) as ws:
    # auth
    resp = await send_and_wait(ws, {"type": "auth", "api_key": api_key}, 10)
    agent_id = resp["agent_id"]
    # agent_card_register JSON 协议
    payload = {
        "type": "agent_card_register",
        "display_name": name,
        "description": description,
        "pipeline_roles": pipeline_roles or [],
        "skills": skills or [],
        "trigger_keyword": trigger_keyword or name,
        "capabilities": capabilities or {"platforms": ["ws-bridge"]},
    }
    await ws.send(json.dumps(payload))
    result = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    assert result["type"] == "agent_card_register_ok"
    return {"agent_id": agent_id, "status": "online"}
```

### C-2 CLI 新增参数

```python
parser.add_argument("--pipeline-roles", default="",
    help='管线角色，逗号分隔，如 "reviewer,qa"')
parser.add_argument("--skills", default="",
    help='技能，逗号分隔，如 "code-review,quality-check"')
```

### C-3 注册后自动验证

在 `register_full_flow()` 末尾，重新连接并查询 Card：

```python
# 验证：重新 auth → 发 agent_card_get → 确认 status=online
verify_ok = await _verify_card(ws_url, api_key, name)
if verify_ok:
    print("  ✅ Agent Card 验证通过")
```

---

## 🅳 回路测试

### D-1 register.py: `_loopback_test()`

在 `register_full_flow()` 末尾（已 auth 连接），向 `_inbox:server` 发 test：

```python
async def _loopback_test(ws, name, agent_id, timeout=15):
    test_id = f"test-{agent_id[:8]}-{int(time.time())}"
    await ws.send(json.dumps({
        "type": "message",
        "channel": "_inbox:server",
        "content": f"test ✅ R96 入驻验证 — {name} 双向通信测试",
        "from_name": name, "agent_id": agent_id,
        "id": test_id, "ts": time.time(),
    }))
    # 等待 server 回复
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if "✅ test 确认" in msg.get("content", ""):
            return True
```

### D-2 handler.py: `_handle_server_relay` test 响应

```python
# handler.py _handle_server_relay() 中增加
if content.startswith("test ✅"):
    logger.info("🔄 Loopback test from %s (%s)", from_name, agent_id[:16])
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": SYSTEM_AGENT_ID,
        "content": f"✅ test 确认 — 双向通信正常（{from_name}）",
        "ts": time.time(),
    })
    return True  # 拦截，不继续转发
```

---

## 编码预检表

| ID | 文件 | 位置 | 改动 | 行数 |
|:---|:-----|:----:|:-----|:----:|
| A-1 | `gateway-plugin/__init__.py` | L166-168 | `url` + `ws_url` 双字段 fallback | +1 |
| A-2 | `gateway-plugin/__init__.py` | L90 | `validate_config()` 同步改 | +1 |
| A-3 | `gateway-plugin/__init__.py` | L170 | `bot_name` + `name` + `display_name` fallback | +3 |
| A-4 | `gateway-plugin/__init__.py` | L179 | `api_key` + `apikey` + `api-key` fallback | +2 |
| B-1 | `gateway-plugin/__init__.py` | api_key 解析后 | 来源诊断日志 | +15 |
| C-1 | `register.py` | `agent_card_register()` | 全函数重写 | ~40 |
| C-2 | `register.py` | `main()` | CLI 参数扩充 | +6 |
| C-3 | `register.py` | `register_full_flow()` | 末尾加自动验证 | +10 |
| D-1 | `register.py` | 新增函数 | `_loopback_test()` | +15 |
| D-2 | `handler.py` | `_handle_server_relay()` | test 前缀拦截 | +15 |
| E-1 | `gateway-config.md` | 全文档 | 字段名对照表 + 配置优先级 + 模板更新 | ~30 |

---

## 验收清单

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 🅰-1 | `extra.ws_url` 被正确读取 | 设 `config.yaml extra.ws_url` → 连接正常 |
| 🅰-2 | `extra.url` 保持兼容 | 回归原有 YAML → 连接正常 |
| 🅰-3 | `extra.name` / `extra.display_name` 做 bot_name fallback | 设 `extra.name` → bot_name 正确 |
| 🅰-4 | `extra.apikey` / `extra.api-key` fallback | 设不同字段名 → api_key 解析正确 |
| 🅱-1 | api_key 来源日志 | 日志显示 `from extra` / `from env` / `from cred file` |
| 🅱-2 | 无 api_key 时错误日志 | 日志显示 `No api_key` + 3 选项 |
| 🅲-1 | 新 bot 运行 register.py 后 Card 在线 | `!agent_card list` 可见 |
| 🅲-2 | `!agent_card get` 完整 | display_name + roles + skills 正确 |
| 🅲-3 | 晓周补注册 Card 成功 | 用晓周 api_key 发 JSON 协议 → list 可见 |
| 🅳-1 | register.py 末尾自动发 `test ✅` | 输出 `📤 已发送 test → _inbox:server` |
| 🅳-2 | server 回复 `✅ test 确认` | bot 收到 → `✅ 双向通信验证通过！🎉` |
| 🅳-3 | 回路测试超时不阻塞 | `⚠️ 回路测试超时（非致命）`, exit 0 |

---

*技术方案编写: 🏗️ 架构师 · 2026-07-11*
