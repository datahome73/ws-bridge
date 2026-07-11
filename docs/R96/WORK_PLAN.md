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
  workspace:
    members:
      - 小开
      - 爱泰
      - 小周
      - 泰虾
      - 小爱
  work_plan_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/dev/docs/R96/WORK_PLAN.md
  requirements_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R96/R96-product-requirements.md
---

# R96 WORK_PLAN — 新 Bot 入驻体验修复

> **状态：** 📋 需求已审核通过 ✅
> **需求文档:** [R96-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R96/R96-product-requirements.md)
> **基线:** `main` latest

---

## 概述

基于新 bot **晓周**（reviewer，`ws_df77eb8e4b15`）入驻实测，修复 3 个 P0 Bug + 新增入驻回路测试功能。

### 团队

| Bot | 角色 | Agent ID | 本轮职责 |
|:----|:-----|:---------|:---------|
| 小开 | 🏗️ arch | `ws_3f7cdd736c1c` | 技术方案 |
| 爱泰 | 💻 dev | `ws_0bb747d3ea2a` | 编码实现 |
| 小周 | 🔍 review | `ws_fcf496ca1b4f` | **主审查** — 代码质量检查 |
| 晓周 | 🔍 review(备选) | `ws_df77eb8e4b15` | **备选审查** — 小周忙时可接手 |
| 泰虾 | 🦐 qa | `ws_eab784ac7652` | 测试验证 |
| 小爱 | 🦸 ops | `ws_c47032fa1f67` | 合并部署 |
| 小谷 | 📋 pm | `ws_f26e585f6479` | 需求+协调 |

---

## Step 1 — PM（需求 + 工作计划）

- [x] R96 需求文档已审核通过（`main@3c47b98`）
- [x] 晓周入驻成功，Agent Card 已注册
- [x] 晓周作为小周**备选**，card 为 `reviewer`，skills=`[code-review, quality-check]`
- [ ] 本 WORK_PLAN 推 dev
- [ ] `!pipeline_start R96`

---

## Step 2 — Arch 技术方案（小开）

**需求：** 为 R96 的 3 个 Bug 修复 + 回路测试功能输出技术方案。

**参考：**
- 需求文档: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R96/R96-product-requirements.md
- 当前 Gateway plugin: `gateway-plugin/__init__.py`
- 当前注册脚本: `skills/ws-bridge-registration/scripts/register.py`
- 服务端 handler: `server/handler.py`（`_handle_server_relay` 部分）
- R87 relay 架构: `docs/R87/R87-product-requirements.md` §4

**3 个 Bug + 1 个新增功能：**

| # | 内容 | 涉及文件 | 改动量估计 |
|:-:|:-----|:---------|:----------:|
| Bug 1 | Gateway extra `url` + `ws_url` 双字段兼容 | `gateway-plugin/__init__.py` | ~2 行 |
| Bug 2 | API key 来源诊断日志 + 文档优先级重排 | `gateway-plugin/__init__.py` + `gateway-config.md` | ~15 行 |
| Bug 3 | register.py `agent_card_register` JSON 协议重写 | `register.py` | ~60 行 |
| 🆕 回路测试 | `_handle_server_relay` 加 `test ✅` 前缀拦截 | `server/handler.py` + `register.py` | ~20 行 |

**技术方案产出：** `docs/R96/R96-tech-plan.md`

**请重点关注：**
1. Gateway plugin 的 `validate_config()` 和 `__init__()` 中 url/api_key 字段读取路径
2. register.py 的 `agent_card_register()` 从 `!命令` 改为 JSON 协议的具体改动
3. `_handle_server_relay()` 中 `test ✅` 前缀的拦截位置（紧挨 R87 relay 旁边）
4. 回路测试的 `_loopback_test()` 函数签名和超时处理
5. **晓周作为 reviewer 备选** — 如果未来小周忙不过来，晓周可以接手 review 任务。技术方案中无需特殊改动，只是管线成员表里多了个 reviewer。

---

## Step 3 — Dev 编码实现（爱泰）

**基于 arch 技术方案实现 3 个 Bug 修复 + 回路测试。**

### 3.1 Bug 1: Gateway extra `ws_url` 兼容

```python
# gateway-plugin/__init__.py
# 改前 L166-168
self._url = normalize_ws_url(extra.get("url") or _env("URL") or "")
# 改后
ws_url_raw = extra.get("url") or extra.get("ws_url") or _env("URL") or ""
self._url = normalize_ws_url(ws_url_raw)
```

同时 `validate_config()` 加 fallback。

### 3.2 Bug 2: API key 来源诊断日志

在 `__init__()` 中 api_key 解析后增加来源日志：

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
    logger.error("[WSBridge] No api_key for '%s'. Options: (1) config.yaml extra.api_key, (2) env WS_IM_API_KEY, (3) ~/.ws-bridge/%s.json", self._bot_name, self._bot_name)
```

### 3.3 Bug 3: register.py `agent_card_register` JSON 协议重写

重写 `agent_card_register()` 函数——发 JSON `{"type": "agent_card_register", ...}` 而非 `!agent_card register` 命令。

同步增加 `--pipeline-roles` 和 `--skills` CLI 参数。

### 3.4 🆕 回路测试

**Server 端**（`handler.py` `_handle_server_relay`）：

```python
# 在 R87 relay 规则前增加
if content.startswith("test ✅"):
    logger.info(f"🔄 Loopback test from {from_name} ({agent_id[:16]})")
    await _send(ws, {
        "type": "broadcast", "channel": f"_inbox:{agent_id}",
        "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
        "content": f"✅ test 确认 — 双向通信正常（{from_name}）", "ts": time.time(),
    })
    return True  # 拦截，不继续转发
```

**Bot 端**（`register.py` `_loopback_test` 函数）：

```python
async def _loopback_test(ws, name, agent_id, timeout=15):
    test_id = f"test-{agent_id[:8]}-{int(time.time())}"
    await ws.send(json.dumps({
        "type": "message", "channel": "_inbox:server",
        "content": f"test ✅ R96 入驻验证 — {name} 双向通信测试",
        "from_name": name, "agent_id": agent_id, "id": test_id, "ts": time.time(),
    }))
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            if "✅ test 确认" in json.loads(raw).get("content", ""):
                return True
    except asyncio.TimeoutError:
        return False
```

**产出：**
- `gateway-plugin/__init__.py` 改动
- `server/handler.py` 改动（_handle_server_relay 加 test 前缀）
- `skills/ws-bridge-registration/scripts/register.py` 重写
- `docs/R94/contrib/gateway-config.md` 文档更新
- 推 dev，commit message 含各改动点

---

## Step 4 — Review 代码审查

**主审查：小周**（晓周作为备选，如果小周忙不过来可接手）

审查重点：
1. ✅ 代码质量 — Gateway plugin 改动是否符合设计
2. ✅ scope 合规 — 只改指定文件，不渗入无关改动
3. ✅ 回路测试 — `test ✅` 前缀是否在 `_handle_server_relay` 中被正确拦截
4. ✅ 兼容性 — 旧 Gateway 配置（`url` 字段）不受影响
5. ✅ register.py — JSON 协议字段是否完整（display_name、pipeline_roles、capabilities dict）

**产出：** `docs/R96/R96-code-review.md`

---

## Step 5 — QA 测试验证（泰虾）

逐项验收测试：

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `extra.ws_url` 字段被正确读取 | 设 `config.yaml extra.ws_url` → Gateway 日志显示 `url=wss://...` |
| 2 | `extra.url` 字段继续保持兼容 | 回归原有配置 → 连接正常 |
| 3 | API key 来源诊断日志完整 | Gateway 日志有 `API key resolved from extra (config.yaml)` |
| 4 | 新 bot 运行 register.py 后 agent_card 在线 | `!agent_card list` 显示新 bot，status=online |
| 5 | register.py 末尾回路测试通过 | 脚本打印 `✅ 双向通信验证通过！🎉` |
| 6 | server 日志记录回路测试 | 日志出现 `🔄 Loopback test from ...` |

**产出：** `docs/R96/R96-test-report.md`

---

## Step 6 — Ops 合并部署归档（小爱）

1. `git checkout main && git merge dev`
2. `git push origin main`
3. Docker 构建部署新镜像
4. 检查 Gateway plugin 日志确认改动生效
5. 关闭工作室
6. TODO.md 更新版本号

---

## 已知风险

| 风险 | 缓解 |
|:-----|:------|
| Gateway plugin 改动影响现有 7 bot | Bug 1/2 都是加 fallback+日志，零行为改变 |
| register.py 重写可能引入新 bug | 测试方案：本地建临时 bot 跑一次全流程 |
| 回路测试在已有 server 上需要重启 | handler.py 改动需 Docker 构建部署，统一在 Step 6 完成 |
