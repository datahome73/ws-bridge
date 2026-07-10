# R96 — 新 Bot 入驻体验修复：Gateway 配置字段 + `.env` API Key + register.py 协议修复 🔧

> **版本：** v1.0（初稿）
> **日期：** 2026-07-11
> **作者：** PM 小谷（基于新 bot 晓周入驻实测反馈）
> **状态：** ⏳ 待审核
> **基线：** `36f6ed8`（main 最新 — R95 pipeline_stop）
> **本轮改动范围：** `gateway-plugin/__init__.py` + `gateway-config.md` + `register.py` + R94 入驻技能文档 + `handler.py`（诊断日志）
> **参考：** `docs/R94/R94-product-requirements.md`（入驻技能标准化轮次）

---

## 0. 触发事件

2026-07-11，新 bot **晓周**（reviewer）通过 R94 入驻技能完成注册接入，实测发现 **3 个阻塞性 Bug**：

| # | 问题 | 严重度 | 首次出现 |
|:-:|:-----|:------:|:--------:|
| 1 | Gateway extra 字段名 `ws_url` → 实际读 `url`，配置被静默吞掉 | 🔴 P0 | 首次安装 |
| 2 | `.env` 设 `WS_IM_API_KEY` 不生效，必须改 `config.yaml extra` 直写 | 🔴 P0 | 首次安装 |
| 3 | **register.py agent_card_register 走了错误的协议路径** — 发 `!agent_card register` 命令（需 admin 权限）而非 JSON `agent_card_register` 协议 → Card 注册静默失败 → 新 bot 在 `!agent_card list` 中不可见 | 🔴 **P0** | 首次注册 |

> **影响：** Bug 3 是最严重的——它导致 R94 入驻技能的核心步骤「Agent Card 注册」完全失效。晓周注册后持有 api_key+agent_id，但没有 Agent Card，在系统中「隐身」：无法被 `@mention` 路由发现、无法参与管线调度、无法在 Web 端看到自己的在线状态。每个后续新入驻的 bot 都会 100% 复现。

---

## 1. Bug 1: Gateway extra 字段名不一致 — `ws_url` vs `url`

### 1.1 问题现象

晓周在 `config.yaml` 的 `extra` 中写了 `ws_url`（因为 `register.py` 的 CLI 参数是 `--ws-url`），但 Gateway 插件只认 `url`。`ws_url` 被静默忽略 → Gateway 日志报 `URL not configured` → bot 无法连接。

### 1.2 根因分析

两个命名约定的断裂：

```yaml
# register.py CLI 参数名
--ws-url  "wss://wsim.datahome73.cloud/ws"

# Gateway 插件 extra 字段名（__init__.py L167）
extra:
  url: "wss://..."          # ✅ 有效
  ws_url: "wss://..."       # ❌ 静默忽略（无报错、无警告）
```

**断裂路径：**

| 环节 | 使用字段名 | 位置 |
|:-----|:-----------|:-----|
| register.py CLI | `--ws-url` | register.py L113 |
| Gateway 配置模板 | `WS_IM_URL`（env var） | gateway-config.md |
| Gateway 插件（extra） | `url` | `gateway-plugin/__init__.py` L167 |
| Gateway 插件（env） | `URL` → `WS_IM_URL` | `gateway-plugin/__init__.py` L167 |
| 新手直觉（晓周） | `ws_url`（跟 CLI 走） | — |

**三个名字指向同一个东西，但互相没有映射关系，新 bot 无处得知正确字段名。**

### 1.3 修复方案

#### 1.3.1 Gateway 插件兼容（免重启修复）

在 `gateway-plugin/__init__.py` 中增加 `ws_url` fallback：

```python
# 改前（L166-168）
self._url = normalize_ws_url(
    extra.get("url") or _env("URL") or ""
)

# 改后
ws_url_raw = extra.get("url") or extra.get("ws_url") or _env("URL") or ""
self._url = normalize_ws_url(ws_url_raw)
```

同时 `validate_config()` 增加 `ws_url` fallback：

```python
# 改前（L90）
url = extra.get("url") or _env("URL")

# 改后
url = extra.get("url") or extra.get("ws_url") or _env("URL")
```

**改动量：** 2 行，零风险。

#### 1.3.2 配置文档统一

`gateway-config.md` 中明确标注：

```yaml
# ✅ extra 支持两种字段名（二选一）
extra:
  url: "wss://..."     # 推荐写法
  # ws_url: "wss://..."  # 备选（兼容 register.py --ws-url 习惯）
```

#### 1.3.3 register.py 输出提示强化

注册成功后，在完成输出中添加一行 Gateway 配置提示：

```python
print(f"  📌 Gateway 配置提示:")
print(f"      config.yaml extra 中写 url（或 ws_url）:")
print(f"        extra:")
print(f"          url: {ws_url}       # ← 注意字段名是 url 不是 ws-url")
```

---

## 2. Bug 2: `.env` 设 `WS_IM_API_KEY` 不生效

### 2.1 问题现象

晓周在 `.env` 中设置：

```env
WS_IM_API_KEY=sk_ws_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Gateway 启动后 api_key 未生效。改为在 `config.yaml` 的 `extra` 中直接设置后恢复正常：

```yaml
gateway:
  platforms:
    ws_bridge:
      extra:
        api_key: sk_ws_xxxxx    # ✅ 生效
```

### 2.2 根因分析

Gateway 插件代码确实支持读取 `WS_IM_API_KEY`（`_env("API_KEY")` → `os.environ.get("WS_IM_API_KEY")`），但 `.env` 不生效的**可能原因**：

| 可能性 | 说明 | 权重 |
|:-------|:-----|:----:|
| **A. .env 加载时机** | Hermes 的 `.env` 加载可能在 Gateway 初始化之后，env vars 尚未注入 `os.environ` | 🔴 最高 |
| **B. .env 文件路径** | 晓周的 `.env` 文件位置不对或文件名不标准 | 🟡 可能 |
| **C. env var 优先级** | `_env_enablement()` 在框架层读取 env → 生成 `extra` dict，但配置合并时 YAML 源的 `extra` 可能覆盖 env 源 | 🟡 可能 |
| **D. env 变量名拼写** | 变量名写错（如 `WS_IM_API_KEY` vs `WS_BRIDGE_API_KEY`） | 🟢 低 |

**为什么 extra 直写能绕开？** 因为 `extra.get("api_key")` 在代码中优先级高于 `_env("API_KEY")`（见 L179），YAML 配置解析后续直接覆盖了 env 源的 early 值。

### 2.3 修复方案

#### 2.3.1 增加 api_key 来源诊断日志

在 Gateway 启动时，明确打印 api_key 的来源：

```python
# 新增诊断日志（在 __init__ 中 api_key 解析完毕后）
if api_key:
    source = "unknown"
    if extra.get("api_key"):
        source = "extra (config.yaml)"
    elif _env("API_KEY"):
        source = "env (WS_IM_API_KEY)"
    else:
        source = f"cred file (~/.ws-bridge/{self._bot_name}.json)"
    logger.warning(
        "[WSBridge] API key resolved from %s (len=%d)",
        source, len(api_key),
    )
else:
    logger.error(
        "[WSBridge] No api_key for '%s'. "
        "Options: (1) config.yaml extra.api_key, "
        "(2) env WS_IM_API_KEY, "
        "(3) ~/.ws-bridge/%s.json",
        self._bot_name, self._bot_name,
    )
```

**改动量：** ~15 行，零业务逻辑风险。

#### 2.3.2 配置文档优先级重排

`gateway-config.md` 中将配置方式按**可靠性降序**排列：

| 优先级 | 方式 | 可靠性 | 建议 |
|:------:|:-----|:------:|:-----|
| 🥇 | config.yaml extra 直写 | ✅ 实测可靠 | **首选推荐** |
| 🥈 | ~/.ws-bridge/{name}.json 凭证文件 | ✅ 自动读取 | 次选（register.py 自动生成） |
| 🥉 | .env 环境变量 | ⚠️ 需确认加载时机 | 仅作 fallback |

配置文件模板改为：

```yaml
# ✅ 推荐：config.yaml extra 直写 api_key
gateway:
  platforms:
    ws_bridge:
      enabled: true
      allow_all: true
      extra:
        url: "wss://wsim.datahome73.cloud/ws"   # 注意字段名是 url（不是 ws_url）
        api_key: "sk_ws_xxxxxxxxxxxxxxxxxxxx"   # 从 register.py 输出获取
        # bot_name: "晓周"                      # 可选，默认从凭证文件读取
```

#### 2.3.3 增加 .env 加载时机检查（Hermes 框架层）

在 Gateway 插件 `validate_config()` 中增加环境探测：

```python
# 在 Gateway 插件 validate_config() 中增加环境探测
if not _env("API_KEY") and not _env("URL") and not _env("BOT_NAME"):
    logger.warning(
        "[WSBridge] No WS_IM_* env vars detected. "
        "Check if .env is loaded before Gateway starts."
    )
```

---

## 3. Bug 3: register.py agent_card_register 用了错误的协议路径（🔴 P0 — 最严重）

### 3.1 问题现象

晓周执行 `register.py` 后：
- ✅ register 协议成功 → 获得 `api_key` + `agent_id`（`ws_df77eb8e4b15`）
- ✅ 凭证文件保存成功
- ❌ Agent Card 注册静默失败 → `!agent_card get ws_df77eb8e4b15` 返回 `No card for agent`
- ❌ `!agent_card list` 只显示 6 个旧 bot，不包含晓周
- ❌ 晓周在系统中「隐身」

### 3.2 根因分析

**服务端有两条独立的 Agent Card 注册路径：**

| 路径 | 消息类型 | 处理函数 | 权限要求 | 适用对象 |
|:-----|:---------|:---------|:--------:|:--------|
| ✅ **JSON 协议**（R72 正确路径） | `{"type": "agent_card_register", ...}` | `handle_agent_card_register()` via `__main__.py` L116-119 | 无额外权限（仅需已认证） | **任何已认证 bot** |
| ❌ **命令路径**（register.py 走的错误路径） | `!agent_card register <id> [--name] [--role]` | `_cmd_agent_card_register()` via 命令分发 | `min_role=3`（管理员） | 仅管理员 |

**register.py 当前错误的做法：**

```python
# register.py → agent_card_register() 函数
# ❌ 错误：发送 type="message" + !agent_card register 命令
await ws.send(json.dumps({
    "type": "message",                         # ← 走广播通道
    "channel": "_admin",
    "content": "!agent_card register --display-name 晓周 --capabilities '{}'",
}))
```

这条消息走的是 `handle_broadcast` → 命令解析 → `_cmd_agent_card_register()`，该函数：
1. 检查 `min_role=3` → 新 bot 是 member（role=2）→ **静默拒绝**（无报错、无日志）
2. 即使权限通过，参数格式也不对——命令期望 `!agent_card register <agent_id> [--name <name>]`，而 register.py 发的是 `--display-name` 和 `--capabilities`

**服务端期望的正确 JSON 协议（R72 设计，已在 __main__.py L116-119 支持）：**

```python
# ✅ 正确：发送 type="agent_card_register" JSON 协议
await ws.send(json.dumps({
    "type": "agent_card_register",          # ← 直接注册，不走广播/命令系统
    "display_name": "晓周",
    "description": "代码审查 bot",
    "pipeline_roles": ["reviewer"],
    "skills": ["code-review", "quality-check"],
    "trigger_keyword": "晓周;review",
    "capabilities": {
        "platforms": ["ws-bridge"],
        "skills": ["code-review", "quality-check"],
    },
}))
```

处理逻辑（`handler.py` L384-440 的 `handle_agent_card_register()`）会：
1. 调用 `ac_mod.register_from_agent(agent_id, msg)` 注册卡片
2. 绑定到当前认证连接的 `agent_id`（自动关联，无需传 agent_id）
3. 返回 `{"type": "agent_card_register_ok", ...}` 确认
4. 触发 R79 欢迎消息 + 管理员通知

### 3.3 修复方案

#### 3.3.1 重写 register.py 的 `agent_card_register()` 函数（核心修复）

将当前的命令路径改为 JSON 协议路径：

```python
async def agent_card_register(
    ws_url: str,
    api_key: str,
    name: str,
    description: str = "",
    capabilities: dict | None = None,
    trigger_keyword: str = "",
    pipeline_roles: list[str] | None = None,
    skills: list[str] | None = None,
) -> dict:
    """
    用 JSON agent_card_register 协议注册 Agent Card。

    流程:
        1. auth(api_key) → auth_ok
        2. {"type": "agent_card_register", ...} → agent_card_register_ok
    """
    async with websockets.connect(ws_url, max_size=2 ** 20,
                                  ping_interval=20, ping_timeout=10) as ws:
        # 1. 认证
        resp = await send_and_wait(ws, {"type": "auth", "api_key": api_key},
                                   AUTH_TIMEOUT)
        if resp.get("type") != "auth_ok":
            raise RuntimeError(f"认证失败: {resp}")
        agent_id = resp.get("agent_id", "?")

        # 2. 发送 JSON agent_card_register 协议
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

        # 3. 等待响应
        response = await asyncio.wait_for(ws.recv(), timeout=10)
        result = json.loads(response)

        if result.get("type") != "agent_card_register_ok":
            raise RuntimeError(f"Agent Card 注册失败: {result}")

        return {
            "agent_id": agent_id,
            "status": "online",
            "display_name": result.get("display_name", name),
        }
```

**改动量：** 整个 `agent_card_register()` 函数重写，~40 行。

#### 3.3.2 register.py main() 新增 CLI 参数

同步增加 `--pipeline-roles` 和 `--skills` 参数：

```python
parser.add_argument(
    "--pipeline-roles", default="",
    help='管线角色列表，逗号分隔，如 "reviewer,qa"（可选）',
)
parser.add_argument(
    "--skills", default="",
    help='技能列表，逗号分隔，如 "code-review,quality-check"（可选）',
)
```

#### 3.3.3 增加注册后自动验证

在 `register_full_flow()` 末尾增加自动验证步骤——重新查询 `!agent_card get` 确认卡片在线。

---

## 4. 附加改进（Low-hanging fruit）

### 4.1 Gateway 多字段兼容

同步增加其他常见误用字段名的兼容 fallback：

| 预期字段 | 兼容 fallback | 来源 |
|:---------|:--------------|:-----|
| `url` | `ws_url` | 开发者 CLI 习惯 |
| `api_key` | `apikey`、`api-key` | 大小写/连字符习惯 |
| `bot_name` | `name`、`display_name` | register.py 概念扩散 |

**原则：** 只做 `or` fallback，不报错，**零侵入静默兼容**。

### 4.2 register.py 与 Gateway 字段名对照表

在 gateway-config.md 末尾增加对照表：

| register.py CLI | Gateway extra | 环境变量 | 说明 |
|:----------------|:--------------|:---------|:-----|
| `--ws-url` | `url`（或 `ws_url`） | `WS_IM_URL` | WebSocket 地址 |
| `--name` | `bot_name` | `WS_IM_BOT_NAME` | Bot 显示名 |
| `--api-key`（无 CLI） | `api_key` | `WS_IM_API_KEY` | 认证密钥 |

---

## 5. 验收标准

### 5.1 Bug 1 验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `extra.ws_url` 字段被正确读取 | 设 `config.yaml extra.ws_url` → Gateway 日志显示 `url=wss://...` |
| 2 | `extra.url` 字段继续保持兼容 | 回归原有配置 → 连接正常 |
| 3 | `validate_config()` 以 `ws_url` 配置不报 `URL not configured` | 设 `extra.ws_url` → validate_config 通过 |
| 4 | 文档明确标注两种字段名 | 检查 `gateway-config.md` |

### 5.2 Bug 2 验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `config.yaml extra.api_key` 正常工作 | Gateway 日志有 `API key resolved from extra (config.yaml)` |
| 2 | `~/.ws-bridge/{name}.json` 凭证文件 fallback 正常 | 删 extra.api_key → Gateway 自动读取凭证文件 |
| 3 | 来源诊断日志完整 | 日志明确显示 `from extra` / `from env` / `from cred file` |
| 4 | 无 api_key 时错误日志清晰 | 日志显示 `No api_key` + 3 种配置选项 |

### 5.3 Bug 3 验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | 新 bot 运行 register.py 后 agent_card 在线 | `!agent_card list` 显示新 bot，status=online |
| 2 | `!agent_card get <agent_id>` 返回完整卡片信息 | display_name、pipeline_roles、skills 正确 |
| 3 | 晓周补注册 Card 成功 | 用晓周 api_key → 发 JSON agent_card_register → `list` 可见 |
| 4 | register.py 末尾自动验证通过 | 脚本打印 `✅ Agent Card 验证通过` |

### 5.4 全流程验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | 新人按新文档从头配置，一次通过 | 仿照晓周流程走一遍，**零报错** |
| 2 | 旧配置不变 | 回归 R94 已有配置，功能无退化 |
| 3 | 晓周在 `!agent_card list` 中可见 | 修复后晓周重新注册 Card 即上线 |

---

## 6. 改动文件清单

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `gateway-plugin/__init__.py` | ~20 行 | url fallback + api_key 来源日志 |
| `docs/R94/contrib/gateway-config.md` | ~30 行 | 字段名对照表 + 配置优先级重排 + 模板更新 |
| `skills/ws-bridge-registration/gateway-config.md` | ~30 行 | 同步仓库版 skill 文档修正 |
| `skills/ws-bridge-registration/scripts/register.py` | **~60 行** | agent_card_register 协议重写 + CLI 扩充 + 自动验证 |
| `docs/R94/contrib/register.py` | ~60 行 | 同步仓库版 register.py |
| `server/__main__.py` | 0 行 | 无需改动（JSON 协议已存在 L116-119） |
| （可选）`docs/TODO.md` | ~3 行 | 更新 v2.62 条目 |

---

## 7. 不在此轮处理的事项

| 事项 | 原因 |
|:-----|:-----|
| 3 个旧 `gateway-plugin/` 副本统一 | 已有合并规划，R96 不扩张范围 |
| Hermes 框架 `.env` 加载时序修复 | 框架层，需大宏决策，可选调研 |
| Web UI 功能增强 | 非入驻体验范畴 |
| 旧 6 bot 卡片的 pipeline_roles 字段统一 | 已在 R73/R78 处理，无新问题 |
| **inbox 消息已送达（sent:1）但目标 bot 未响应** | 晓周实测发现。可能原因：无 Agent Card 导致路由异常 / Gateway 未配通 / 框架层 inbox 消费 bug。**等大宏 TG 调查结果后决定是否纳入 R96 范围** |
