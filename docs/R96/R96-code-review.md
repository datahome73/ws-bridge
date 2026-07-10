# R96 代码审查报告 — 新 Bot 入驻体验修复 🔧

> **审查人：** 🔍 小周
> **审查基准：** `c9b0522` (R95) → `71e9c8b` (R96)
> **改动文件：** `gateway-plugin/__init__.py` (+26/-2) · `server/handler.py` (+20/-0) · `skills/scripts/register.py` (+166/-43)
> **参考文档：** `docs/R96/R96-tech-plan.md` · `docs/R96/R96-product-requirements.md`

---

## 审查结论：🟢 通过

5/5 检查项全部通过。4 项改动精确对应技术方案，字段兼容性完善，回路测试逻辑安全。

---

## 🅰️ gateway-plugin ws_url fallback

**判定：🟢 通过**

### 改动

2 处增添 `extra.get("ws_url")` fallback：

```python
# validate_config() ~L90
url = extra.get("url") or extra.get("ws_url") or _env("URL")

# __init__() ~L166
self._url = normalize_ws_url(
    extra.get("url") or extra.get("ws_url") or _env("URL") or ""
)
```

### 兼容性矩阵

| 场景 | `extra.url` | `extra.ws_url` | 结果 | 状态 |
|:-----|:-----------:|:--------------:|:-----|:----:|
| 旧配置（仅 `url`） | `"wss://..."` | 无 | `url` 优先 | ✅ 不变 |
| 新配置（仅 `ws_url`） | 无 | `"wss://..."` | `ws_url` fallback | ✅ 新能力 |
| 两者都有 | `"wss://..."` | `"wss://..."` | `url` 优先 | ✅ 保持旧行为 |
| 都空 | 无 | 无 | `_env("URL")` 兜底 | ✅ 向后兼容 |

### 一致性检查

| 检查项 | 状态 |
|:-------|:----:|
| 两处改动完全相同（DRY 可接受） | ✅ |
| `ws_url` 在 `url` 之后作为 fallback（优先级正确） | ✅ |
| 空值保护 `or ""` | ✅ |
| `normalize_ws_url()` 包裹 | ✅ |

---

## 🅱️ gateway-plugin API Key 来源诊断日志

**判定：🟢 通过**

### 诊断逻辑

```python
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
    logger.error("[WSBridge] No api_key for '%s'. Options: (1) extra.api_key, (2) env WS_IM_API_KEY, (3) ~/.ws-bridge/%s.json",
                 self._bot_name, self._bot_name)
```

| 场景 | 日志 | 行为 |
|:-----|:-----|:------|
| api_key 来自 `config.yaml` | ✅ `resolved from extra (config.yaml)` | 日志辅助诊断 |
| api_key 来自 `.env` | ✅ `resolved from env (WS_IM_API_KEY)` | 确认 env 生效 |
| api_key 来自凭证文件 | ✅ `resolved from cred file (~/.ws-bridge/xxx.json)` | 确认文件读取 |
| api_key 缺失 | ✅ `logger.error` 列出 3 种方案 | 引导修复 |

**⚠️ 日志级别说明：** 成功解析使用 `logger.warning`（而不是 `logger.info`）。这不是错误——`warning` 级别确保在默认日志配置下不被过滤，对新 bot 入驻调试可见。符合预期。

---

## 🅲 register.py JSON 协议重写

**判定：🟢 通过**

### 协议变更

| 维度 | 改动前 | 改动后 |
|:-----|:-------|:-------|
| 注册方式 | `!agent_card register` 命令到 `_admin` | `agent_card_register` JSON 协议消息 |
| 依赖 | 需 admin 权限 | 无需权限 |
| 角色字段 | 无 | `pipeline_roles` + `skills` |
| 回路测试 | 无 | 注册后自动执行 |

### Payload 字段完整性

```python
payload = {
    "type": "agent_card_register",    # ✅ 正确消息类型
    "agent_id": agent_id,              # ✅ 来自 auth_ok 响应
    "display_name": name,               # ✅ bot 名称
    "capabilities": capabilities or {},  # ✅ 能力描述
    "pipeline_roles": pipeline_roles or [],  # 🆕 管线角色
    "skills": skills or [],                 # 🆕 技能列表
    "trigger_keyword": trigger_keyword or "", # ✅ 触发关键词
}
```

| 字段 | 来源 | 状态 |
|:-----|:-----|:----:|
| `type` | 硬编码 `"agent_card_register"` | ✅ |
| `agent_id` | `auth` 响应中的 `agent_id` | ✅ 正确传递 |
| `display_name` | CLI `--name` 参数 | ✅ |
| `capabilities` | CLI `--capabilities` 参数（JSON 解析） | ✅ |
| `pipeline_roles` | CLI `--pipeline-roles`（JSON 数组） | 🆕 |
| `skills` | CLI `--skills`（JSON 数组） | 🆕 |
| `trigger_keyword` | CLI `--trigger-keyword` 参数 | ✅ |

### CLI 参数完整性

| 参数 | 类型 | 默认 | 状态 |
|:-----|:-----|:-----|:----:|
| `--name` | 位置参数 | 必填 | ✅ |
| `--capabilities` | JSON 字符串 | `"{}"` | ✅ |
| `--pipeline-roles` | JSON 数组字符串 | `"[]"` | 🆕 |
| `--skills` | JSON 数组字符串 | `"[]"` | 🆕 |
| `--trigger-keyword` | 字符串 | `""` | ✅ |
| `--ws-url` | 字符串 | `DEFAULT_WS_URL` | ✅ |
| `--loopback-test` | store_true | `True` | 🆕 |
| `--no-loopback-test` | store_false | — | 🆕 |

### JSON 解析安全

```python
try:
    pipeline_roles = json.loads(args.pipeline_roles)
except json.JSONDecodeError as e:
    print(f"❌ pipeline-roles JSON 解析失败: {e}")
    sys.exit(1)
```

✅ 三项 JSON 参数（capabilities / pipeline_roles / skills）均有 try/except 保护。
✅ 格式错误时打印清晰指导后退出。

---

## 🅳 回路测试 test 前缀拦截

**判定：🟢 通过**

### 拦截位置

```python
async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    content = (msg.get("content") or "").strip()
    # ── R96: 回路测试拦截 ── (handler.py L6313)
    if content.startswith("test ✅"):
        # 回复确认到 bot inbox
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "content": f"✅ test 确认 — 双向通信正常（{from_name}）",
            ...
        })
        return True  # ← 拦截，停止 relay
    # ── R87: relay 逻辑 ──
    if not is_server_inbox(channel):
        return False
    ...
```

### 安全分析

| 检查项 | 结果 |
|:-------|:-----|
| 在 relay 逻辑之前拦截 | ✅ 运行在 `is_server_inbox` 检查之前 |
| 拦截信号精确 | ✅ `content.startswith("test ✅")` — 极低误触 |
| `return True` 停止转发 | ✅ test 消息不会意外传给 PM |
| `_send` 回复到 `_inbox:<agent_id>` | ✅ 使用函数参数 `agent_id`（已认证） |
| 回复 payload 字段完整 | ✅ `type`/`channel`/`from_name`/`from_agent`/`content`/`ts` |
| `try/except` 保护 | ✅ 异常不阻断后续 relay 逻辑 |

### 回路测试客户端（register.py）

```python
async def _loopback_test(ws, name, agent_id, timeout=15):
    payload = {
        "content": f"test ✅ R96 入驻验证 — {name} 双向通信测试",
        "channel": "_inbox:server",
        ...
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

| 检查项 | 结果 |
|:-------|:-----|
| `_inbox:server` 通道 | ✅ 与 R87 relay 集成 |
| `test ✅` 前缀 | ✅ 与 server 端 `startswith` 匹配 |
| 确认检测 | ✅ `"✅ test 确认" in content` — 精确匹配 |
| 15s 超时 | ✅ `asyncio.wait_for` + deadline 循环 |
| 失败不影响注册 | ✅ caller `try/except Exception` 捕获 |
| 用户提示友好 | ✅ 成功 🎉 / 超时 ⚠️ / 异常 ⚠️ |

**⚠️ 微瑕：** `_loopback_test` 内部未 catch `asyncio.TimeoutError`——异常会传播到 `register_full_flow` 的 `except Exception` 兜底。不影响功能但消息略有差异（显示"回路测试异常"而非"回路测试超时"）。建议后续迭代在 `_loopback_test` 内加 `try/except TimeoutError` 使超时和异常的错误信息区分。

---

## 兼容性 — 旧 url 字段不受影响

**判定：🟢 通过**

```python
# 改前 (已有)
url = extra.get("url") or _env("URL")

# 改后 (R96)
url = extra.get("url") or extra.get("ws_url") or _env("URL")
```

`extra.get("url")` 仍然在第一位，旧配置 100% 不变。 ✅

---

## Scope 合规 — 只改指定文件

**判定：🟢 通过**

| 文件 | 改动 | 对应方案 |
|:-----|:-----|:---------|
| `gateway-plugin/__init__.py` | 🅰️ Bug 1 (ws_url) + 🅱️ Bug 2 (diag) | ✅ |
| `server/handler.py` | 🅳 回路测试 server 端拦截 | ✅ |
| `skills/scripts/register.py` | 🅲 JSON 协议 + 🅳 回路测试客户端 | ✅ |
| 其余文件 | docs / docs / docs | 文档仅追加，无代码 |

**零 scope creep 确认。** ✅

---

## 额外发现

### 注册完成后回显改进

`register_full_flow` 末尾新增了回路测试结果和清晰的下一步指引：

```bash
  ⏳ 正在执行回路测试... (向 _inbox:server 发送 test ✅)
  ✅ 回路测试通过！🎉 双向通信正常
  📌 下一步: 配置 Hermes Gateway 实现持续连接
     参考: gateway-config.md
```

这直接回应了入驻体验报告中"新 bot 首次连接后不知道该干嘛"的问题。 ✅

### v. 技术方案一致性

| 方案条目 | 实现 | 状态 |
|:---------|:-----|:-----|
| ✅ `validate_config` + `__init__` 处加 `ws_url` fallback | 2 处均修改 | ✅ |
| ✅ 优先级 `url > ws_url > env` | 保持 | ✅ |
| ✅ api_key 来源诊断日志 | 3 来源全覆盖 | ✅ |
| ✅ register.py JSON 协议 | `agent_card_register` 替代 `!命令` | ✅ |
| ✅ `--pipeline-roles` / `--skills` CLI 参数 | JSON 数组解析 | ✅ |
| ✅ 回路测试 server 拦截 | `_handle_server_relay` 最前 | ✅ |
| ✅ 回路测试客户端 | `register_full_flow` 尾部 | ✅ |

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:------|
| 🅰️ ws_url fallback | 🔴 | 🟢 | 2 处一致，优先级正确 |
| 🅱️ api_key 诊断日志 | 🔴 | 🟢 | 3 来源全覆盖，缺失列出选项 |
| 🅲 JSON 协议完整 | 🔴 | 🟢 | payload 字段齐全，CLI 参数完备 |
| 🅳 回路测试拦截 | 🔴 | 🟢 | 位置正确，`return True` 拦截 |
| 旧 url 兼容 | 🔴 | 🟢 | `url` 优先序不变 |
| Scope 合规 | 🟢 | 🟢 | 3 源代码文件精确对应 |
| 与技术方案一致性 | 🟢 | 🟢 | 7/7 条目匹配 |

**最终结论：🟢 通过** — R96 四项改动精准修复入驻体验问题。ws_url fallback 优先级正确，诊断日志全覆盖，JSON 协议注册无需 admin 权限，回路测试端到端验证双向通信。3 文件+零 creep。可进入 Step 5 🦐 QA 测试。

---

*报告编写: 🔍 小周 · 2026-07-11*
