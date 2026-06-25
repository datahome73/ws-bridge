# R40 开发计划 — Web 端 GitHub OAuth 认证

> **版本：** v1.0 ✅（已审批）
> **状态：** ✅ 已审核
> **日期：** 2026-06-25
> **需求文档：** [R40-product-requirements.md](R40-product-requirements.md)

---

## 角色分工

| 角色 | 成员 |
|:----:|:----:|
| 🦸 项目管理 | admin-bot |
| 🧐 需求分析师 | pm-bot |
| 🏗️ 架构师 | arch-bot |
| 💻 开发工程师 | dev-bot |
| 🔍 审查工程师 | review-bot |
| 🦐 测试工程师 | qa-bot |

---

## 开发步骤

### 🔶 前置决策区（全部通过）

#### ✅ Step A — 需求文档 🧐 pm-bot ✅
- **v1.0 ✅（项目负责人审核通过）**
- GitHub OAuth 2.0 认证，与现有绑定码并行
- 身份映射表：GitHub 用户名 → 显示昵称
- 不改 Bot 认证，不改绑定码入口

#### ✅ Step B — 工作计划 🦸 admin-bot ✅
- ✅ v1.0 已审核通过

---

### 🟢 自动化管线

#### ✅ Step 1 — 创建工作室 🦸 admin-bot ✅

| 事项 | 说明 |
|:-----|:------|
| 工作室 | R40 开发工作室 |
| 目标 | 全员加入，准备点名 |
| 状态 | ✅ 已创建 — 6/6 成员，双 admin（小爱+泰虾），通道已切 |

#### ⬜ Step 2 — 点名 🦐 qa-bot

| 事项 | 说明 |
|:-----|:------|
| 点名主持 | qa-bot |
| 关键操作 | MSG_SET_ACTIVE_CHANNEL → ws:R40开发工作室 |
| 全员回复 | 「已切」确认后点名完成 |

#### ⬜ Step 3 — 技术方案 🏗️ arch-bot

> 产出：`docs/R40/R40-tech-plan.md`

**改动范围确认：** 仅第④类（Web 端），涉及文件：

| 文件 | 改动内容 |
|:-----|:---------|
| `server/web_viewer.py` | 新增 3 个路由：`/auth/github/login`、`/auth/github/callback`、`/api/auth/me`；修改 `setup_routes()` |
| `server/templates.py` | 修改 `BIND_TEMPLATE`：增加 GitHub 登录按钮和样式 |
| `server/config.py` | 新增 GitHub OAuth 配置项：`GITHUB_OAUTH_CLIENT_ID`、`GITHUB_OAUTH_CLIENT_SECRET`、`GITHUB_OAUTH_REDIRECT_URI`、`OAUTH_NAME_MAP` |

**关键技术要点：**

1. **GitHub OAuth 流程（2 个 HTTP 请求）**
   - `POST https://github.com/login/oauth/access_token` → 换 token
   - `GET https://api.github.com/user` → 取身份（login, name, email）
   - 使用 ws-bridge 已有的 `aiohttp` 或 `urllib`，无需第三方库

2. **身份映射**
   - 从 `OAUTH_NAME_MAP` 环境变量解析映射表
   - 匹配的 GitHub 用户 → 显示昵称
   - 未匹配的 → 回退为 GitHub login

3. **Session 存储**
   - 复用 `persistence.set_web_sessions()` / `persistence.get_web_sessions()`
   - OAuth session 与绑定码 session 共存，`validate_token()` 不改
   - Cookie 复用 `ws_im_session`（7 天）

4. **State 参数防 CSRF**
   - OAuth 请求携带随机 state，回调时校验

5. **配置缺失保护**
   - 未设 `GITHUB_OAUTH_CLIENT_ID` 时，页面不显示 GitHub 登录按钮

#### ⬜ Step 4 — 编码 💻 dev-bot

**编码清单：**

1. **`config.py`** — 新增 4 个环境变量常量
2. **`web_viewer.py`** — 新增路由和 OAuth 回调处理
3. **`templates.py`** — 修改 `BIND_TEMPLATE`，新增 OAuth 登录按钮 UI
4. **`persistence.py`** — 无需改动（session 存储机制已有）

**Commit 格式：** `feat(R40): <描述>`

#### ⬜ Step 5 — 代码审查 🔍 review-bot

审查重点：

- OAuth 回调中的 CSRF state 校验
- token 和 secret 不在日志中泄露
- `OAUTH_NAME_MAP` 解析健壮性（空值、格式错误）
- 配置缺失时 GitHub 登录按钮不显示
- 错误路径不暴露敏感信息

#### ⬜ Step 6 — 测试验证 🦐 qa-bot

| # | 验证项 | 验证方法 |
|:-:|:-------|:---------|
| V-1 | 绑定码登录正常 | 现有用户通过绑定码登录，确认功能无回归 |
| V-2 | GitHub 登录按钮可见 | 未配 OAuth 时不显示；配置后显示 |
| V-3 | GitHub 完整登录流程 | 点击按钮 → GitHub 授权 → 回调 → 进入聊天界面 |
| V-4 | Cookie 持久化 | 登录后关闭浏览器重新打开，无需重新登录 |
| V-5 | 身份映射生效 | 映射表中的用户显示对应昵称 |
| V-6 | 未映射用户可登录 | 回退显示 GitHub 用户名 |
| V-7 | 服务重启不丢失 | 重启容器后 OAuth session 依然有效 |
| V-8 | state 校验 | 伪造回调无 state/state 错误时拒绝 |

#### ⬜ Step 7 — 合并部署 + 归档 🦸 admin-bot

- `git checkout main && git merge dev && git push origin main`
- 部署正式容器
- 更新 `docs/TODO.md`
- 关闭工作室

---

## 关键约束

1. **不改绑定码** — 现有登录方式完全保留，不做任何移除或修改
2. **不改 Bot 认证** — 仅 Web 端，各虾的 WS 连接认证方式不变
3. **不引入第三方库** — GitHub OAuth 用标准 HTTP 请求实现
4. **OAuth 配置缺失时优雅降级** — 仅隐藏 GitHub 登录按钮，不影响绑定码
