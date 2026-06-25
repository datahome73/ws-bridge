# R40 产品需求 — Web 端 Google OAuth 认证

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
- 用户通过 Telegram 私聊将码发给内部管理员审批
- 审批通过后返回 token，写入 `localStorage` + cookie（7 天有效期）

**安全问题：**

1. **绑定码可被截获** — 绑定码在浏览器端明文显示，任何人只要看到码就能申请审批
2. **每 2s 轮询生成新码** — 旧码立即失效，但码的生命周期窗口内仍可被利用
3. **无身份鉴别** — 绑定码不绑定用户身份，只确认「这个浏览器被允许进入」
4. **审批依赖人工** — 必须由内部管理员在 Telegram 私聊中手动审批，缺乏用户自助能力

### 1.2 项目负责人的考量

正是由于当前认证机制的不安全性，项目负责人至今未在 Web 端直接与团队沟通，所有方向决策、授权操作均在 Telegram 私聊中完成。期望通过引入安全的 OAuth 认证，为后续在 Web 端建立直接沟通渠道奠定基础。

---

## 2. 设计方案

### 2.1 整体流程

引入 Google OAuth 2.0 Authorization Code + PKCE 流程，与现有绑定码认证并行运行：

```
┌─────────────────────────────────────────────────────┐
│               Web 端登录页                            │
│                                                      │
│   ┌─────────────────┐   ┌───────────────────────┐   │
│   │ 🔑 绑定码登录     │   │ 🌐 使用 Google 账号登录  │   │
│   │ （现有，保留）     │   │ （新增）               │   │
│   └─────────────────┘   └─────────┬─────────────┘   │
│                                   │                  │
└───────────────────────────────────┼──────────────────┘
                                    │
                                    ▼
               ┌─────────────────────────────────────┐
               │  Google OAuth 授权页                   │
               │  （accounts.google.com）               │
               │                                        │
               │  用户选择 Google 账号 → 授权             │
               └─────────────────┬───────────────────┘
                                 │ 回调到 ws-bridge
                                 ▼
               ┌─────────────────────────────────────┐
               │  /auth/google/callback               │
               │                                        │
               │  ① 用 code 换 token                    │
               │  ② 验证 ID token（JWT 签名验）           │
               │  ③ 从 ID token 提取 email + name       │
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

### 2.3 Google OAuth 配置

需要在 Google Cloud Console 中创建 OAuth 2.0 Client：

| 配置项 | 值 |
|:-------|:----|
| Application type | Web application |
| Authorized redirect URIs | `{WS_BRIDGE_URL}/auth/google/callback` |
| 所需 scope | `openid`, `email`, `profile` |

配置信息通过以下环境变量注入：

| 环境变量 | 说明 |
|:---------|:------|
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth Client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth Client Secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | 回调地址（如 `https://ws-bridge.example.com/auth/google/callback`） |

### 2.4 无额外 Python 依赖

OAuth 流程中与服务端纯 HTTP 请求相关的操作（token exchange、公钥获取）使用 ws-bridge 已有的 `aiohttp` 或 Python 标准库 `urllib` 即可完成，无需新增第三方 OAuth 库。ID token 解码和签名验证用标准 JWT 流程实现。

---

## 3. 用户体验变化

### 3.1 登录页（新增按钮）

当前绑定码页面下方增加 Google 登录按钮：

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
│  [ 🌐 使用 Google 账号登录 ]  │  ← 新增
└─────────────────────────────┘
```

### 3.2 登录流程

| 步骤 | 用户操作 | 系统行为 |
|:----:|:---------|:---------|
| 1 | 点击「使用 Google 账号登录」 | 重定向到 `accounts.google.com` OAuth 授权页 |
| 2 | 选择 Google 账号，点击授权 | Google 回调 ws-bridge |
| 3 | — | 服务端验证身份，生成 session，Set-Cookie |
| 4 | 自动进入聊天界面 | 无感登录，后续访问自动携带 cookie |

### 3.3 登录后体验

与绑定码登录完全一致：

- 聊天界面不变，所有 Tab、消息、功能完全可用
- 退出后用相同 Google 账号再次登录，恢复同一身份
- 支持多个 Google 账号同时登录（不同浏览器/设备）
- `validate_token()` 返回的 viewer 名为 Google 账号的 email 或 display name

### 3.4 过渡期行为

| 场景 | 行为 |
|:-----|:------|
| 已有绑定码 token 的用户 | 继续使用，不受影响 |
| 新用户打开 Web 页面 | 看到绑定码 + Google 登录两个选项 |
| 通过 Google 登录成功后 | 后续访问自动携带 cookie，无需重新登录 |
| 通过绑定码登录成功后 | 后续访问自动携带 cookie，与现有行为一致 |
| OAuth 稳定运行一段时间 | 项目负责人评估后，再决定是否关闭绑定码入口 |

---

## 4. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| O-1 | 绑定码登录不受影响，现有用户无感知 | 🔴 P0 |
| O-2 | 点击「使用 Google 账号登录」跳转到 Google OAuth 授权页 | 🔴 P0 |
| O-3 | Google 授权回调后，正常进入聊天界面，看到所有频道和消息 | 🔴 P0 |
| O-4 | OAuth 登录成功后 `ws_im_session` cookie 写入（7 天），刷新页面无需重新登录 | 🔴 P0 |
| O-5 | OAuth session token 存入 `persistence.set_web_sessions()`，服务重启后不丢失 | 🔴 P0 |
| O-6 | 多个用户通过不同 Google 账号登录，各自独立 session | 🟡 P1 |
| O-7 | Google 登录失败（如拒绝授权、网络错误）时显示错误提示，不卡死页面 | 🟡 P1 |
| O-8 | OAuth 配置缺失时（未设 `GOOGLE_OAUTH_CLIENT_ID`），页面不显示 Google 登录按钮 | 🟡 P1 |
| O-9 | 同一 Google 账号在多个设备登录，各自独立 session | 🟢 P2 |

---

## 5. 不纳入本次需求

| 事项 | 原因 |
|:-----|:------|
| Bot 认证方式修改 | 明确约定本轮仅改 Web 端，Bot 认证方式不变 |
| 特殊频道（项目负责人沟通频道） | 先完成 OAuth 认证，后续轮次再讨论 |
| 取消现有绑定码登录 | 过渡策略：OAuth 稳定后再评估关闭 |
| 权限体系与 OAuth 角色绑定 | 当前 OAuth 仅解决「你是谁」，不涉及「你能做什么」 |
| Nous Portal OAuth（备选方案） | 经评估 Google OAuth 实现更轻量、更通用 |

---

## 6. 开放问题

| # | 问题 | 状态 |
|:-:|:-----|:----:|
| Q1 | Google OAuth 回调的 redirect URI 是什么？（需要确认 ws-bridge 的部署域名） | ⏳ 待项目负责人确认 |
| Q2 | Google OAuth Client ID 和 Secret 由谁创建？（需要在 Google Cloud Console 操作） | ⏳ 待项目负责人确认 |
| Q3 | OAuth 登录成功后 viewer 名称用 email 还是 Google display name？ | ⏳ 待项目负责人确认 |
