# R40 代码审查报告

**审查对象：** commit `cc7cb3e` — feat(R40): GitHub OAuth login flow
**审查者：** 🔍 小周
**审查日期：** 2026-06-25
**状态：** 🔴 **不通过**

---

## 审查项结果

| # | 审查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | CSRF state 校验 | 🟢 通过 | `secrets.token_hex(16)` 生成 + callback 校验 |
| 2 | token/secret 日志泄露 | 🟢 通过 | 日志仅记录异常对象，无敏感字段 |
| 3 | OAUTH_NAME_MAP 解析健壮性 | 🟢 通过 | try/except JSONDecodeError 静默失败 |
| 4 | 配置缺失时按钮隐藏 | 🔴 **不通过** | 按钮始终可见；且 JS 被破坏 |
| 5 | 错误路径信息泄露 | 🟢 通过 | 通用错误文本，无敏感信息 |
| 6 | 重复路由注册 | 🔴 **不通过** | `/api/agents/status` 注册两次 |

---

## 致命问题（阻止合并）

### 🔴 F-1: BIND_TEMPLATE 页面 JS 被破坏（templates.py L46-L49）

**位置：** `server/templates.py` 第 46-49 行

R40 修改在 `<script>` 块内插入了 3 行：
```html
<script>
// R40: Hide GitHub login button if OAUTH_CLIENT_ID is not configured
// (server returns 501 when unconfigured, so the link simply errors out)
</script>
async function init() {
  ...
```

**问题：** 新增的 `</script>` 关闭标签（L49）将原来的 JS 代码截断。`async function init()` 被移到了 `<script>` 标签**外部**，浏览器将其视为纯文本而非 JavaScript，不会执行。

**后果：** 绑定页面（BIND_TEMPLATE）的 `init()` 函数完全不执行——
  - 绑定码（bind code）不显示
  - 轮询授权状态不工作
  - 页面永久卡在「等待授权中...」

**修复方案：** 移除第 49 行的 `</script>`，把隐藏按钮的逻辑内联到原有 `<script>` 块中，或在 `init()` 内加判断。

---

### 🔴 F-2: 重复路由注册（web_viewer.py L534-L535）

**位置：** `server/web_viewer.py` 第 534-535 行

```python
    app.router.add_get("/api/agents/status", handle_api_agents_status)
    app.router.add_get("/api/agents/status", handle_api_agents_status)  # ← 重复！
```

**问题：** `/api/agents/status` 路由被注册了两次。aiohttp 的 `add_get` 不允许重复注册同一路径（`ValueError: Route already registered`）。

**后果：** 应用启动时抛出异常，服务完全无法启动。

**修复方案：** 删除第 535 行的重复注册。

---

## 重要问题（建议修复）

### ⚠️ W-1: OAuth state 单值存储 — 并发竞争条件（web_viewer.py L406）

```python
request.app["oauth_state"] = state  # 单值，后一个覆盖前一个
```

两个用户同时发起 GitHub 登录时，后面的 state 会覆盖前面的。前一个用户的 callback 会拿到错误的 state，导致 CSRF 校验失败（403）。

**建议：** 改用 dict 存储 `request.app["oauth_states"] = {state: True}`，callback 时 `pop` 删除。

---

### ⚠️ W-2: redirect_uri 未 URL 编码（web_viewer.py L409-L411）

```python
github_url = (
    "https://github.com/login/oauth/authorize?"
    "client_id=" + client_id + "&"
    "redirect_uri=" + redirect_uri + "&"  # ← 未编码
    "state=" + state + "&"
    "scope=read:user"
)
```

如果 `redirect_uri` 包含特殊字符（如 `&` 或 `?`），会破坏 URL 结构。应用 `urllib.parse.quote(redirect_uri, safe='')` 后再拼接。

---

### ⚠️ W-3: Cookie 缺少 secure=True（web_viewer.py L490-L497）

```python
resp.set_cookie(
    "ws_im_session", token,
    max_age=604800,
    httponly=True,
    samesite="Lax",
    # missing: secure=True
    path="/",
)
```

GitHub OAuth 预期在 HTTPS 环境下使用，session cookie 应标记 `secure=True`，否则 cookie 可能被中间人截获。如当前环境支持 HTTPS，应添加该标记。

---

### ⚠️ W-4: 默认 redirect_uri 使用 0.0.0.0（config.py L25）

```python
os.environ.get("WS_PUBLIC_URL", "http://0.0.0.0:8765") + "/auth/github/callback"
```

当 `WS_PUBLIC_URL` 未设置时，默认值为 `http://0.0.0.0:8765`。`0.0.0.0` 是监听地址，不是客户端可访问的域名/IP。GitHub 会拒绝注册此 redirect_uri。部署时必须显式设置 `GITHUB_OAUTH_REDIRECT_URI` 为实际公网地址。

---

## 通过项详情

### 🟢 CSRF state 校验
- 使用 `secrets.token_hex(16)`（64 字符 hex）生成高强度随机 state
- callback 时严格比较 `state == stored_state`
- 攻击者无法伪造 state，防止 CSRF 攻击

### 🟢 token/secret 不泄露至日志
- `logger.error("GitHub OAuth token exchange failed: %s", e)` — 只记录异常对象
- `logger.error("GitHub user fetch failed: %s", e)` — 同上
- 未记录 `access_token`、`client_secret`、`code`、`state` 等敏感字段

### 🟢 OAUTH_NAME_MAP 解析健壮
- `try/except JSONDecodeError` 捕获格式异常
- 解析失败时静默保留空 dict，不抛出异常

### 🟢 错误路径不暴露敏感信息
- "Missing code or state parameter" — 不暴露变量值
- "Invalid state (CSRF)" — 攻击者无法利用
- "OAuth token exchange failed" — 通用
- "Failed to fetch GitHub user" — 通用
- "Could not determine GitHub username" — 通用
- "OAuth not configured" (501) — 不暴露环境细节

---

## 审查结论

| 项 | 值 |
|----|-----|
| **结果** | 🔴 **不通过** |
| **阻塞项** | F-1（JS 破坏）+ F-2（重复路由） |
| **建议修复** | W-1 ~ W-4（并发、编码、安全、默认值） |
| **通过项** | 1, 2, 3, 5（CSRF/日志/解析/错误信息） |

**修复要求：** 必须先修正 F-1（BIND_TEMPLATE JS 截断）和 F-2（重复路由注册），建议同时处理 W-1~W-4，然后重新提交审查。
