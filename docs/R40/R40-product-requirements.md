# R40 产品需求 — Web 端 GitHub OAuth 认证

> **版本：** v0.1（草稿，待项目负责人审核）
> **状态：** 📋 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-25
> **本轮改动范围：** 仅第④类（Web 端）+ 对应服务端 API 路由

---

## 1. 背景与痛点

### 1.1 当前绑定码认证不安全

ws-bridge Web 端目前使用绑定码（bind code）作为登录认证方式：

- 用户打开 `/chat` → 显示绑定码页面
- 前端 JS 每隔 ~2s 轮询 `/api/bind` 生成新码
- 用户通过 TG 私聊将码发给内部管理员审批
- 审批通过后返回 token，写入 `localStorage` + cookie（7 天有效期）

**安全问题：**

1. **绑定码可被截获** — 绑定码在浏览器端明文显示，任何人只要看到码就能申请审批
2. **每 2s 轮询生成新码** — 旧码立即失效，但码的生命周期窗口内仍可被利用
3. **无身份鉴别** — 绑定码不绑定用户身份，只确认「这个浏览器被允许进入」
4. **审批依赖人工** — 必须由内部管理员在 TG 私聊中手动审批，缺乏用户自助能力

### 1.2 项目负责人的考量

正是由于当前认证机制的不安全性，项目负责人至今未在 Web 端直接与团队沟通，所有方向决策、授权操作均在 TG 私聊中完成。期望通过引入安全的 OAuth 认证，为后续在 Web 端建立直接沟通渠道奠定基础。

---

## 2. 设计方案

### 2.1 整体流程

引入 **GitHub OAuth 2.0** Authorization Code 流程，与现有绑定码认证并行运行：

```
┌─────────────────────────────────────────────────────┐
│               Web 端登录页                            │
│                                                      │
│   ┌─────────────────┐   ┌───────────────────────┐   │
│   │ 🔑 绑定码登录     │   │ 🐙 使用 GitHub 登录    │   │
│   │ （现有，保留）     │   │ （新增）               │   │
│   └─────────────────┘   └─────────┬─────────────┘   │
│                                   │                  │
└───────────────────────────────────┼──────────────────┘
                                    │
                                    ▼
               ┌─────────────────────────────────────┐
               │  GitHub OAuth 授权页                   │
               │  (github.com/login/oauth/authorize)   │
               │                                        │
               │  用户授权 → 回调到 ws-bridge             │
               └─────────────────┬───────────────────┘
                                 │ code + state
                                 ▼
               ┌─────────────────────────────────────┐
               │  /auth/github/callback               │
               │                                        │
               │  ① POST code → GitHub → 换 access_token│
               │  ② GET api.github.com/user → 获取身份   │
               │  ③ 身份映射：login → 内部显示名          │
               │  ④ 生成内部 session token               │
               │  ⑤ 存入 persistence (复用 session 存储)  │
               │  ⑥ Set-Cookie: ws_im_session=xxx       │
               └─────────────────┬───────────────────┘
                                 │ 重定向到 /chat
                                 ▼
               ┌─────────────────────────────────────┐
               │  /chat (有 cookie)                   │
               │                                        │
               │  validate_token() → 识别 OAuth 用户     │
               │  进入聊天界面，与绑定码用户完全一致       │
               └─────────────────────────────────────┘
```

### 2.2 与现有架构的兼容

**关键设计原则：不改变现有认证基础设施。**

- **Token 存储复用** — OAuth 登录生成的 session token 存入 `persistence.set_web_sessions()`，与绑定码 token 在同一个存储中
- **验证函数复用** — `validate_token()` 无需改动，因为 OAuth session 和绑定码 session 在同一份存储中
- **Cookie 复用** — 使用相同的 `ws_im_session` cookie 名称，7 天有效期
- **并行运行** — 绑定码认证不做任何改动，两种方式均可登录

### 2.3 身份映射

OAuth 拿到的 GitHub 用户名需要映射为 Web 聊天室显示的昵称。通过配置映射表实现：

```env
# 配置项：OAUTH_NAME_MAP
# 格式：GitHub用户名=昵称,多个用逗号分隔
# 示例：OAUTH_NAME_MAP=github_user=ProjectOwner,other_user=Nickname
```

未在映射表中的 OAuth 用户：
- 仍可成功登录进入聊天界面
- 显示名回退为 GitHub 用户名（`login` 字段）
- 后续可通过更新配置添加映射条目

### 2.4 GitHub OAuth 配置

项目负责人在 `github.com/settings/developers` → OAuth Apps 创建应用：

| 配置项 | 值 |
|:-------|:----|
| Application name | `WS Bridge` |
| Homepage URL | ws-bridge 部署域名 |
| Authorization callback URL | `{WS_BRIDGE_URL}/auth/github/callback` |

配置信息通过环境变量注入：

| 环境变量 | 说明 |
|:---------|:------|
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App 的 Client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App 的 Client Secret |
| `GITHUB_OAUTH_REDIRECT_URI` | 回调地址（与 GitHub OAuth App 配置一致） |
| `OAUTH_NAME_MAP` | 身份映射表（示例：`github_user=ProjectOwner`） |

### 2.5 无额外 Python 依赖

GitHub OAuth 流程仅需两个 HTTP 请求，使用 ws-bridge 已有的 `aiohttp` 或 Python 标准库 `urllib` 即可完成：

1. **换 token** — `POST https://github.com/login/oauth/access_token` 带 `code` + `client_id` + `client_secret`
2. **取身份** — `GET https://api.github.com/user` 带 `Authorization: Bearer [ACCESS_TOKEN]`

无需引入任何第三方 OAuth 库。

---

## 3. 用户体验变化

### 3.1 登录页（新增按钮）

当前绑定码页面下方增加 GitHub 登录按钮：

```
┌─────────────────────────────┐
│  🌉 WS Bridge 聊天室          │
│                              │
│  ┌─────────────────────┐    │
│  │     WEB-XXXX         │    │  ← 绑定码（现有，不变）
│  └─────────────────────┘    │
│  ⏳ 等待授权中...             │
│                              │
│  ──── 或 ────                │
│                              │
│  [ 🐙 使用 GitHub 登录 ]     │  ← 新增
└─────────────────────────────┘
```

### 3.2 登录流程

| 步骤 | 用户操作 | 系统行为 |
|:----:|:---------|:---------|
| 1 | 点击「使用 GitHub 登录」 | 重定向到 `github.com/login/oauth/authorize` |
| 2 | 点击授权 | GitHub 回调 ws-bridge（带 `code`） |
| 3 | — | 服务端换 token → 取身份 → 生成 session → Set-Cookie |
| 4 | 自动进入聊天界面 | 后续访问自动携带 cookie，无感登录 |

### 3.3 登录后体验

与绑定码登录完全一致：

- 聊天界面不变，所有 Tab、消息、功能完全可用
- 显示名根据身份映射表决定：GitHub 用户名 → 映射的昵称
- 退出后用同一 GitHub 账号再次登录，恢复同一身份
- 支持多个 GitHub 账号同时登录（不同浏览器/设备）
- `validate_token()` 返回的 viewer 名为映射后的显示名

### 3.4 过渡期行为

| 场景 | 行为 |
|:-----|:------|
| 已有绑定码 token 的用户 | 继续使用，不受影响 |
| 新用户打开 Web 页面 | 看到绑定码 + GitHub 登录两个选项 |
| 通过 GitHub 登录成功后 | 后续访问自动携带 cookie，无需重新登录 |
| 通过绑定码登录成功后 | 后续访问自动携带 cookie，与现有行为一致 |
| OAuth 稳定运行一段时间 | 项目负责人评估后，再决定是否关闭绑定码入口 |

---

## 4. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| O-1 | 绑定码登录不受影响，现有用户无感知 | 🔴 P0 |
| O-2 | 点击「使用 GitHub 登录」跳转到 GitHub OAuth 授权页 | 🔴 P0 |
| O-3 | GitHub 授权回调后，正常进入聊天界面，看到所有频道和消息 | 🔴 P0 |
| O-4 | OAuth 登录成功后 `ws_im_session` cookie 写入（7 天），刷新页面无需重新登录 | 🔴 P0 |
| O-5 | OAuth session token 存入 `persistence.set_web_sessions()`，服务重启后不丢失 | 🔴 P0 |
| O-6 | 身份映射表生效：映射表中的 GitHub 用户登录后显示为对应昵称 | 🔴 P0 |
| O-7 | 多个用户通过不同 GitHub 账号登录，各自独立 session | 🟡 P1 |
| O-8 | GitHub 登录失败（拒绝授权、网络错误）时显示错误提示，不卡死页面 | 🟡 P1 |
| O-9 | OAuth 配置缺失时（未设 `GITHUB_OAUTH_CLIENT_ID`），页面不显示 GitHub 登录按钮 | 🟡 P1 |
| O-10 | 未在映射表中的 GitHub 用户可登录，显示名回退为 GitHub 用户名 | 🟢 P2 |

---

## 5. 不纳入本次需求

| 事项 | 原因 |
|:-----|:------|
| Bot 认证方式修改 | 明确约定本轮仅改 Web 端，Bot 认证方式不变 |
| 特殊频道（项目负责人沟通频道） | 先完成 OAuth 认证，后续轮次再讨论 |
| 取消现有绑定码登录 | 过渡策略：OAuth 稳定后再评估关闭 |
| 权限体系与 OAuth 角色绑定 | 当前 OAuth 仅解决「你是谁」，不涉及「你能做什么」 |

---

## 6. 开放问题（已收敛）

### 6.1 决策记录

| # | 问题 | 决策 | 体现 |
|:-:|:-----|:-----|:-----|
| Q1 | redirect_uri 是什么路径？ | 技术方案根据部署域名确定，统一为 `/auth/github/callback` | §2.4 回调 URL |
| Q2 | 用 Google 还是 GitHub？ | GitHub OAuth，项目负责人熟悉 GitHub 生态，团队成员也使用同一仓库 | §2 整节 |
| Q3 | 登录后显示什么名称？ | 通过身份映射表：GitHub 用户名 → 映射的昵称（项目负责人指定） | §2.3 身份映射 |
