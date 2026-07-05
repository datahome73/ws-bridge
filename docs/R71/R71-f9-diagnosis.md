# R71 F-9 Web 端诊断报告 🩺

> **诊断日期：** 2026-07-05
> **诊断者：** 项目管理（代开发工程师）
> **Web URL：** `https://wsim.datahome73.cloud/chat`
> **基线 commit：** `b3ed0cd`
> **现状：** 远程探测 + 代码分析，浏览器实测需有效 session token

---

## §1 基本信息

| 项目 | 值 |
|:-----|:----|
| Web 服务 URL | `https://wsim.datahome73.cloud` |
| Web 框架 | aiohttp（同进程启动，`__main__.py` `main()`） |
| 身份认证 | GitHub OAuth（R40）+ 绑定码（R8，后备） |
| 前端模板 | `server/templates.py` CHAT_TEMPLATE（684 行内联 JS/CSS/HTML） |
| API 路由 | `server/web_viewer.py` setup_routes（531 行） |
| 画廊/历史 | `server/workspace_api.py`（35 行） |
| 管线状态 | Web 容器 v2.36（基线 `b3ed0cd`） |

---

## §2 Phase A — 进程与端口检查 ✅

| 检查项 | 结果 | 说明 |
|:-------|:----:|:-----|
| `GET /health` | ✅ `ok` | 基础健康检查正常 |
| `GET /api/health` | ✅ 200 | `{"status":"ok","connections":6,"agents_online":6}` |
| `GET /` | ✅ 200 (1,869B) | BIND_TEMPLATE 登录页正常渲染 |
| `GET /chat` | ✅ 200 (1,869B) | 同 BIND_TEMPLATE（未认证时） |
| GitHub OAuth 跳转 | ✅ | 点击"使用 GitHub 登录"正确跳转 GitHub |
| `GET /api/channels` | ✅ 200 | 返回 lobby + 40+ 个工作室（含 R71-dev 已归档） |
| `GET /api/chat?channel=lobby` | ✅ 401 | 无 token 时返回 401，正常 |
| `GET /api/health (verbose)` | ✅ | 6 个连接在线 |

**结论：** Web 容器进程存活、端口监听正常、API 端点全部响应。**进程/端口层无问题。**

---

## §3 Phase B — 浏览器 DevTools 分析（远程 + 代码）

> ⚠️ 因无可用 web session token（GitHub OAuth 需交互登录），浏览器 DevTools 实测用代码分析替代。

### 3.1 前端加载链路

```
用户访问 /chat
  → handle_chat() 检查 cookie/query token
    → 无有效 token → BIND_TEMPLATE（登录页）
    → 有有效 token → CHAT_TEMPLATE + JS init()
      → init() 流程:
        1. 恢复 localStorage tab2 状态
        2. fetch /api/workspaces → 设置活跃工作室
        3. renderTabBar() → 渲染 Tab 栏
        4. selectTab(firstTab) → loadMessages(channel)
        5. connectWS() → WebSocket 实时推送
        6. setInterval(5000) → 轮询 /api/chat
        7. setInterval(15000) → 轮询 /api/workspaces
        8. setInterval(15000) → 轮询 /api/status
```

### 3.2 `loadMessages()` 关键代码路径

```javascript
async function loadMessages(channel) {
    list.innerHTML = '加载中...';          // ← "加载中..." 设置点
    const resp = await fetch('/api/chat...');
    if (!resp.ok) {
        if (resp.status === 401) {
            location.href = '/chat';       // → bind 页（不是 F-9 场景）
            return;
        }
        list.innerHTML = '加载失败';        // ← "加载失败"（不是"加载中"）
        return;
    }
    const data = await resp.json();
    const msgs = data.messages || [];
    list.innerHTML = '';                   // 正常渲染
    // ... 渲染消息
}
```

**"加载中..." 持久化的可能路径：**

| # | 场景 | 是否匹配 F-9 | 可能性 |
|:-:|:-----|:-----------:|:------:|
| ① | `fetch()` 无 timeout → 网络卡住 → `await` 永远挂起 | ✅ Tab栏可见，加载中不消失 | 🟡 中 |
| ② | `init()` 在 `selectTab()` 前崩溃 → `loadMessages` 从未调用 | ❌ Tab栏也不会渲染 | 🔴 低 |
| ③ | `/api/chat` 200 返回但 `resp.json()` 非 JSON 异常 | → catch 块显示"网络异常" | 🔴 低 |
| ④ | 轮询 `setInterval` 中 `if (!resp.ok) return;` 静默失败 | ✅ 但初始 loadMessages 已成功则不出现 | 🟡 中 |
| ⑤ | 轮询中 `msgs.length > existing.length` 触发 `loadMessages()` 重置 | ✅ 但仅闪一下，非持久 | 🟡 中 |

### 3.3 轮询路径静默失败（重要发现）

```javascript
// Line 489-502: 轮询 fallback
setInterval(async function() {
    const resp = await fetch('/api/chat...');
    if (!resp.ok) return;          // ← 静默失败！不更新 UI
    const data = await resp.json();
    // ...
    if (msgs.length > existing.length) {
        loadMessages(channel);     // ← 重新设置"加载中..."
    }
}, 5000);
```

**关键发现：** 轮询路径 `if (!resp.ok) return;` 是静默的。但更重要的——**`loadMessages` 在轮询中被增量检测调用时，会重新设置 "加载中..."**（line 277）。如果此时网络暂时挂起，用户会看到短暂的"加载中..."闪现。

### 3.4 console.error 排查（代码审查）

模板中所有异步操作都包裹了 `try/catch`（`catch(_) {}`），不会有未捕获的异常。但 **fetch 调用没有设置 timeout**（`AbortSignal.timeout`），以下路径可能 hang：

| 调用点 | 超时设置 | 风险 |
|:-------|:-------:|:----:|
| `loadMessages()` 中 fetch `/api/chat` | ❌ 无 | 服务器慢或无响应 → 永久"加载中" |
| `renderWsPanel()` 中 fetch `/api/workspaces` | ❌ 无 | 静默 catch |
| 轮询中 fetch `/api/chat` | ❌ 无 | 静默 `return` |

---

## §4 Phase C — 日志分析

> 无 VPS SSH 权限，无法执行 `docker logs`。通过 WS 管道间接检查。

| 检查项 | 结果 | 说明 |
|:-------|:----:|:-----|
| WebSocket 连接数 | ✅ 6 在线 | `/api/health` 显示 6 agents online |
| 聊天消息传递 | ✅ 正常 | WS 客户端可正常收发消息 |
| 工作室归档 | ✅ R71-dev 已归档 | 多次 restart 后正常归档 |

---

## §5 Phase D — Token/Session 检查

| 检查项 | 结果 | 说明 |
|:-------|:----:|:-----|
| `/api/bind` 绑定码生成 | ✅ 正常 | 返回 `WEB-8V8V` |
| `/api/approve_web` 绑定码审批 | ⛔ localhost only | 仅允许 127.0.0.1 调用 |
| GitHub OAuth | ✅ 正常跳转 | 正确重定向到 GitHub 登录 |
| Cookie (`ws_im_session`) | 7天有效期 | `handle_github_callback` 设置 |
| web sessions 持久化 | `_web_sessions.json` | 随 DATA_DIR 保存/加载 |

**结论：** web session 机制正常，但无法从远程创建有效 token。

---

## §6 根因结论

### 🎯 主要结论：Web 容器运行正常，F-9 无法远程复现

基于完整的远程探测和代码分析：

```
Web 服务器状态: ✅ 正常
API 端点:       ✅ 全部响应
认证流程:       ✅ GitHub OAuth + 绑定码均正常
前端代码:       ⚠️ 发现 2 个潜在问题（见 §6.1）
```

### 🎯 最可能的根因假设（按优先级）

| # | 假设 | 说明 | 代码位置 |
|:-:|:-----|:------|:---------|
| **H-1** 🔴 P0 | **fetch 无 timeout** — `loadMessages()` 中 `/api/chat` 请求无超时保护，网络波动时"加载中..."永久停留 | `templates.py` L279 |
| **H-2** 🔴 P0 | **Token 过期但 cookie 未清** — `loadMessages` 返回 401 → `location.href = '/chat'` → cookie 仍存在 → 服务器返回 CHAT_TEMPLATE（坏 token）→ 无限重定向循环 | `templates.py` L282-286 |
| **H-3** 🟡 P1 | **轮询增量触发 reload** — 新消息到达时轮询调用 `loadMessages()`，每次重置为"加载中..."，若响应慢则用户感知为卡住 | `templates.py` L499-500 |
| **H-4** 🟡 P1 | **WebSocket 断连重连期间无数据** — `onclose` 3s 后重连，断连期间轮询也失败（死锁窗口） | `templates.py` L476-484 |
| **H-5** 🟢 P2 | **服务端 `_web_sessions.json` 数据卷丢失** — 部署后 sessions 空，但用户 localStorage 存有旧 token | 部署级问题 |

### 🎯 结论陈述

> **根因：** F-9 的综合原因是 **前端 `/api/chat` 请求缺乏超时保护**（H-1），结合 **Token 过期循环**（H-2），导致用户看到 Tab 栏但消息区保持"加载中..."。在慢网络或服务器重启后的 session 丢失场景下，这两个问题叠加产生持久"加载中..."状态。

---

## §7 修复建议

### 🅱️ 顺手修复（≤30 行，本轮可做）

| # | 修复 | 位置 | 改动 |
|:-:|:-----|:-----|:-----|
| **F-1** | `loadMessages()` 添加 10s AbortSignal | `templates.py` L279 | `const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 10000);` |
| **F-2** | 轮询中 `if (!resp.ok)` 时显示状态指示（非静默） | `templates.py` L494-495 | 添加 `list.innerHTML = '<div class="empty">连接异常，正在重试...</div>'` |
| **F-3** | 轮询中避免增量触发 `loadMessages`（改为 append） | `templates.py` L499-500 | 用增量 append 替代全量 `loadMessages()` |

**示例代码（F-1 + F-2）：**
```diff
 async function loadMessages(channel) {
   const list = document.getElementById('msgList');
   list.innerHTML = '<div class="empty">加载中...</div>';
+  const controller = new AbortController();
+  const timeout = setTimeout(() => controller.abort(), 10000);
   try {
-    const resp = await fetch('/api/chat?channel=' + ...);
+    const resp = await fetch('/api/chat?channel=' + ..., {signal: controller.signal});
+    clearTimeout(timeout);
     if (!resp.ok) {
       if (resp.status === 401) {
         try { localStorage.removeItem('ws_bridge_token'); } catch(e) {}
         location.href = '/chat'; return;
       }
       list.innerHTML = '<div class="empty">加载失败（请刷新重试）</div>'; return; }
     const data = await resp.json();
+  } catch(e) {
+    clearTimeout(timeout);
+    list.innerHTML = '<div class="empty">⏱ 连接超时，请刷新重试</div>';
+    return;
   }
```

**轮询增量修复（F-3）：**
```diff
-    if (msgs.length > existing.length) {
-      loadMessages(channel);
+    const newMsgs = msgs.slice(existing.length);
+    for (let i = 0; i < newMsgs.length; i++) {
+      appendMessage(channel, newMsgs[i]);
     }
```

### ⚠️ 排期修复（R72，建议）

| # | 修复 | 说明 |
|:-:|:-----|:------|
| F-4 | WebSocket 重连时显示状态条 | 非阻塞 UI，仅状态指示 |
| F-5 | 前端添加全局 fetch timeout 拦截器 | 所有 API 调用统一超时保护 |

### ❌ 不修（架构/配置级）

| # | 说明 | 原因 |
|:-:|:------|:-----|
| F-6 | session 持久化改造 | 当前 `_web_sessions.json` 已落盘，非代码问题 |
| F-7 | 前端框架重构 | 改动 >200 行，专有轮次 |

---

## §8 降级说明

| 场景 | 降级策略 | 是否触发 |
|:-----|:---------|:--------:|
| 浏览器不可达 | 代码分析替代 DevTools | ✅ 已执行 |
| Token 不可获取 | 通过代码分析推论 | ✅ 已执行 |
| 无 VPS SSH | WS 命令管道 + HTTP API 探测 | ✅ 已执行 |

---

## §9 诊断结论摘要

```
Phase A 进程/端口: ✅ 正常
Phase B DevTools:  ⚠️ 无法远程复现，代码分析识别 2 个问题
Phase C 日志:      ⚠️ 无 SSH，间接推断正常
Phase D Token:     ✅ 机制正常

根因: 前端 fetch 超时保护缺失(H-1) + Token 过期循环(H-2)
分类: 代码小修（≤30 行）
推荐: 顺手修复 F-1 + F-2 + F-3（3 个 patch，共 ~25 行净增）
```
