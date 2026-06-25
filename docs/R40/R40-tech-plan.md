# R40 技术方案 — Web 端 GitHub OAuth 登录

> **版本：** v1.0
> **状态：** 📝 初稿
> **架构师：** 🏗️ 小开
> **日期：** 2026-06-25
> **依据：** R39 验证结论（F-9/F-10/F-11 处理 + Web 端体验增强）

---

## 1. 总体设计

### 1.1 需求背景

当前 Web 端登录流程：`/api/bind` 生成 WEB 绑定码 → 管理员（小爱）在 TG 审批 → 轮询 `/api/check` 拿到 token → 进入聊天室。

**痛点：**
- 大宏（项目负责人）每次需发码 → 等审批 → 手动操作
- 绑定码 5 分钟 TTL，过期需重新生成
- 审批需管理员在线，非自助

**R40 方案：** 增加 **GitHub OAuth 登录** 作为第二登录方式，允许大宏通过 GitHub 账号一级授权直接进入，绑定码流程保留作为备选。

### 1.2 架构变更

```
 ┌─────────────┐    OAuth     ┌──────────────┐
 │  浏览器      │  ────────→   │  GitHub.com   │
 │  Web 端      │  ←────────   │  OAuth App    │
 └──────┬──────┘   code+token └──────────────┘
        │
        │ POST /auth/callback
        ▼
 ┌──────────────────────────────────────────┐
 │  web_viewer.py                            │
 │  ┌──────────────────────────────────┐     │
 │  │  handle_auth_login()             │     │ ← /auth/login → redirect to GitHub
 │  │  handle_auth_callback()          │     │ ← /auth/callback → exchange code→token→create session
 │  │  OAUTH_NAME_MAP                  │     │ ← 硬编码 GitHub login → 中文显示名映射
 │  └──────────────────────────────────┘     │
 └──────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────┐    ┌──────────────────┐
 │  persistence.py   │    │  templates.py     │
 │  set_web_sessions()│    │  BIND_TEMPLATE     │
 │  (复用现有方法)     │    │  + GitHub 按钮     │
 └──────────────────┘    └──────────────────┘
```

**设计原则：**
- **复用现有 session 体系** — OAuth 登录后写入同一个 `_web_sessions.json`，`validate_token()` 零改动
- **不持久化 access_token** — 仅单次 /user 查询，最小权限原则
- **优雅降级** — `GITHUB_OAUTH_ENABLED` 为 False 时不注册路由、不渲染按钮
- **双入口自动覆盖** — 路由通过 `setup_routes()` 统一注册

### 1.3 涉及文件

| 文件 | 改动类型 | 预估行数 |
|:----|:--------|:--------:|
| `server/config.py` | 修改 | ~+4 行 |
| `server/web_viewer.py` | 修改 | ~+90 行 |
| `server/templates.py` | 修改 | ~+15 行 |

---

## 2. 详细设计

### 2.1 Config — 新增 GitHub OAuth 配置项

**文件：** `server/config.py`

```python
# ── R40: GitHub OAuth ──────────────────────────────────────────
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI", "")
GITHUB_OAUTH_ENABLED = bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET and GITHUB_REDIRECT_URI)
```

**设计理由：** 四个环境变量覆盖完整 OAuth 配置。`OAUTH_ENABLED` 由前三个推导，减少一项重复配置。设为 False 时全局禁用。

### 2.2 Web Viewer — OAuth Handler 新增（~90 行）

**文件：** `server/web_viewer.py`

#### 2.2.1 State 管理（内存表，防 CSRF）

```python
# ── R40: OAuth state store (in-memory, CSRF protection) ────
_oauth_states: dict[str, dict] = {}  # state → {created_at, redirect}
_OAUTH_STATE_TTL = 300  # 5 minutes
```

**设计理由：**
- State 为 `secrets.token_urlsafe(32)`，不可预测
- 5 分钟 TTL + 用完即删（callback 成功后立即删除）
- 内存存储，不需要持久化（token 交换是一次性的）

#### 2.2.2 `/auth/login` — 跳转到 GitHub

```python
async def handle_auth_login(request: web.Request) -> web.Response:
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"created_at": time.time(), "redirect": "/chat"}
    # Cleanup expired states
    _cleanup_oauth_states()
    redirect_url = (
        f"https://github.com/login/oauth/authorize?"
        f"client_id={config.GITHUB_CLIENT_ID}&"
        f"redirect_uri={config.GITHUB_REDIRECT_URI}&"
        f"state={state}&"
        f"scope=read:user"
    )
    raise web.HTTPFound(redirect_url)
```

**scope 选择：** `read:user` — 仅读取公开资料和 email，不可读写仓库/issue/其他资源。

#### 2.2.3 `/auth/callback` — 接收 code + state

```python
async def handle_auth_callback(request: web.Request) -> web.Response:
    error = request.query.get("error")
    if error:
        return web.Response(text=f"GitHub 授权失败: {error}", status=400)

    code = request.query.get("code", "")
    state = request.query.get("state", "")

    # Validate state (CSRF protection)
    if state not in _oauth_states:
        return web.Response(text="State 不匹配，请重新登录", status=400)
    del _oauth_states[state]  # One-time use

    # Exchange code for access_token
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        ) as resp:
            token_data = await resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            return web.Response(text=f"Token 交换失败: {token_data.get('error_description', 'unknown')}", status=400)

        # Fetch user info
        async with session.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            user_data = await resp.json()

    github_login = user_data.get("login", "")
    github_name = user_data.get("name", "") or github_login

    # Map to Chinese display name
    viewer_name = OAUTH_NAME_MAP.get(github_login.lower(), github_name)

    # Create session via existing persistence
    import hashlib
    raw = f"github:{github_login}:{time.time()}:{secrets.token_hex(8)}"
    token = hashlib.sha256(raw.encode()).hexdigest()

    sessions = persistence.get_web_sessions()
    sessions[token] = {
        "name": viewer_name,
        "created_at": time.time(),
        "source": "github_oauth",
        "github_login": github_login,
    }
    persistence.set_web_sessions(sessions)

    # Set cookie + redirect
    resp = web.HTTPFound("/chat")
    resp.set_cookie(
        "ws_im_session",
        token,
        max_age=604800,     # 7 days (same as bind-code sessions)
        httponly=True,
        samesite="Lax",
        path="/",
    )
    raise resp
```

#### 2.2.4 身份映射表

```python
# ── R40: GitHub login → Chinese display name mapping ────────
# Code-level hardcoded mapping, no external config file needed.
# When GitHub login is NOT in this map, falls back to github's `name` (then `login`).
OAUTH_NAME_MAP: dict[str, str] = {
    "datahome": "大宏",
    # Add more mappings as needed:
    # "some-github-id": "显示名",
}
```

**设计理由：** 硬编码在代码中，避免额外 JSON 配置文件。不匹配时优雅 fallback 到 GitHub 的 name 字段。

#### 2.2.5 辅助函数

```python
def _cleanup_oauth_states() -> None:
    """Remove expired OAuth states."""
    now = time.time()
    expired = [k for k, v in _oauth_states.items()
               if now - v["created_at"] > _OAUTH_STATE_TTL]
    for k in expired:
        del _oauth_states[k]
```

#### 2.2.6 Route 注册（条件性）

在 `setup_routes()` 中：

```python
def setup_routes(app: web.Application) -> None:
    # ... existing routes unchanged ...

    # R40: GitHub OAuth (only registered when configured)
    if config.GITHUB_OAUTH_ENABLED:
        app.router.add_get("/auth/login", handle_auth_login)
        app.router.add_get("/auth/callback", handle_auth_callback)
```

**关键设计点：** 条件注册确保 `OAUTH_ENABLED=False` 时路由不存在，连 404 都返回不了 OAuth 相关内容。

### 2.3 Templates — BIND_TEMPLATE 增加 GitHub 按钮

**文件：** `server/templates.py`

在 BIND_TEMPLATE 的 `<p>` 说明文字下方，绑定码框上方，增加条件渲染：

```html
<!-- R40: GitHub OAuth (conditionally rendered by server) -->
{GITHUB_OAUTH_BUTTON}
```

通过 Python 端的字符串替换实现条件渲染：

```python
# In handle_chat() - 不是 BIND_TEMPLATE 的静态字符串，而是动态拼接
if config.GITHUB_OAUTH_ENABLED:
    github_button = '<a href="/auth/login" class="github-btn">'
    github_button += '<svg>...</svg> GitHub 账号登录'
    github_button += '</a>'
    bind_html = BIND_TEMPLATE.replace("{GITHUB_OAUTH_BUTTON}", github_button)
else:
    bind_html = BIND_TEMPLATE.replace("{GITHUB_OAUTH_BUTTON}", "")
```

CSS 新增（在 BIND_TEMPLATE 的 `<style>` 块中）：

```css
.github-btn{display:inline-flex;align-items:center;gap:8px;
  background:#24292f;color:#fff;padding:10px 24px;border-radius:8px;
  text-decoration:none;font-size:0.95rem;margin-bottom:20px;
  transition:background .2s;}
.github-btn:hover{background:#2d333b;}
.github-btn svg{width:20px;height:20px;}
```

---

## 3. 向后兼容性

| 场景 | 影响 | 说明 |
|:----|:----:|:-----|
| `GITHUB_OAUTH_ENABLED=False` | ✅ 无影响 | 路由不注册，按钮不渲染，绑定码流程完全不变 |
| 已有 session token | ✅ 无影响 | OAuth 创建的 session 与绑定码 session 格式一致 |
| 旧浏览器（无 OAuth 支持） | ✅ 无影响 | 绑定码流程照常可用 |
| 多设备同时登录 | ✅ 无影响 | 每个 OAuth 登录生成独立 session |
| 同时使用 GitHub + 绑定码 | ✅ 无影响 | 两套登录方式完全独立，可同时存在 |

---

## 4. 验收验证

### 4.1 对应需求 A — GitHub OAuth 登录

| # | 验收项 | 验证方式 | 预期 |
|:-:|:-------|:--------|:-----|
| A-1 | `/auth/login` 跳转到 GitHub 授权页 | 浏览器访问 | 302 到 `github.com/login/oauth/authorize` |
| A-2 | 授权后自动跳回 `/auth/callback?code=...&state=...` | 完整流程 | 200，cookie 设置成功，重定向到 `/chat` |
| A-3 | callback 中 state 校验 | 篡改 state 参数 | 400 "State 不匹配" |
| A-4 | 登录后在 `/chat` 看到正确的中文显示名 | 打开 Web 端 | 右上角显示"大宏" |
| A-5 | session 持久化（重启后仍可登录） | 重启容器 + 刷新页面 | 仍保持登录状态（7天内） |
| A-6 | GitHub 按钮在 `OAUTH_ENABLED=False` 时不显示 | 删除环境变量重启 | BIND_TEMPLATE 无 GitHub 按钮 |
| A-7 | OAUTH_NAME_MAP 不匹配时 fallback | 用未映射的 GitHub 账号登录 | 显示 GitHub 的 name 而非中文名 |
| A-8 | 绑定码登录仍可用 | 绑定码流程走一遍 | 与 OAuth 互不干扰 |

### 4.2 安全矩阵

| 威胁 | 防御 | 严重度 |
|:-----|:-----|:------:|
| CSRF（攻击者伪造 callback） | `state` 32-byte random + 一次性使用 | 🔴 P0 |
| Access token 泄露 | 不持久化 + 单次查询后丢弃 | 🔴 P0 |
| Scope 权限过大 | `read:user` 最小 scope，无 repo/org 权限 | 🟡 P1 |
| OAuth code 重放 | code 一次性（GitHub 侧保证），state 一次性（服务端保证） | 🟡 P1 |
| 未授权访问 /auth/login | 无需保护，登录入口天然公开 | 🟢 P2 |

---

## 5. 配置清单

部署时需配置以下环境变量：

| 变量 | 示例值 | 必填 | 说明 |
|:-----|:-------|:----:|:-----|
| `GITHUB_CLIENT_ID` | `Iv23...` | 🔴 | GitHub OAuth App 的 Client ID |
| `GITHUB_CLIENT_SECRET` | `6a3f...` | 🔴 | GitHub OAuth App 的 Client Secret |
| `GITHUB_REDIRECT_URI` | `https://domain/auth/callback` | 🔴 | 必须在 GitHub App 的 Callback URL 中注册 |

**GitHub OAuth App 注册步骤：**
1. 进入 GitHub Settings → Developer settings → OAuth Apps → New OAuth App
2. Application name: `WS Bridge`
3. Homepage URL: `https://domain/`
4. Authorization callback URL: `https://domain/auth/callback`
5. 注册后获取 CLIENT_ID 和 CLIENT_SECRET

---

## 6. 不需要做的

| 不纳入项 | 理由 |
|:---------|:-----|
| 多 OAuth Provider（Google/GitLab） | 本轮只做 GitHub，GitHub 是开发者最常用的账号 |
| OAuth 登录后的角色/权限区分 | 所有 OAuth 登录者都是 viewer 角色，与绑定码一致 |
| Access token 刷新 | 不持久化 token，session 7天到期后重新登录 |
| OAuth 用户退出后同步删除 session | 复杂度高，7 天自动过期已足够 |
| `/auth/login` 的 rate limit | OAuth 本身有 GitHub 侧限速，服务端无需额外限制 |

---

> **审核记录：**
> - v1.0 提交方向审查：2026-06-25
> - 方向审查结论：🟢 **通过**（架构清晰，改动收敛，关键技术点全部落实）
> - 审查建议：
>   1. `_exchange_code_for_token()` 加 `aiohttp.ClientTimeout(total=10)` + 1 次重试（编码时处理）
>   2. `handle_chat()` token 丢失时显式走降级回 bind 页面（编码时处理）
