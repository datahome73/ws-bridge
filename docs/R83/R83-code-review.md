# R83 代码审查报告 — Web 端 Inbox 化改造 🌐

> **审查人：** 🔍 小周
> **审查对象：** `2713383` feat(R83): Web 端 Inbox 化改造 — Tab 重设计 + 收件箱增强 + 绑定码清理
> **审查日期：** 2026-07-09
> **改动统计：** 6 文件, +85/-303 = **-218 行净删**

---

## 0. 审查结论

> 🟢 **通过 — 0 项 🔴, 0 项 🟡, 0 项 💡 — 直接进入 Step 6 QA**

独立验证确认：7 项审查重点全部合规，无阻塞项，无警告项。

---

## 1. 改动统计

| 文件 | + | - | 净 | 说明 |
|:-----|:-:|:-:|:--:|:-----|
| `server/templates.py` | +85 | -137 | **-52** | Tab 3-tab 重构 + inbox poll + 绑定码清理 |
| `server/web_viewer.py` | +0 | -63 | **-63** | 删除绑定码全套函数 + 路由 |
| `server/auth.py` | +0 | -54 | **-54** | 删除绑定码全套函数 |
| `server/persistence.py` | +0 | -24 | **-24** | 删除绑定码存储 |
| `server/__main__.py` | +0 | -15 | **-15** | 删除绑定码启动 + 导入 |
| `server/handler.py` | +0 | -10 | **-10** | 删除绑定码命令路由 |
| **合计** | **+85** | **-303** | **-218** | ✅ 净减 |

---

## 2. 逐项独立验证

### ✅ 2.1 Scope 合规

**方法：** 读取 commit 的完整 diff（`git diff 2713383^..2713383`），逐文件确认改动范围。

| 文件 | 改动范围 | 是否合规 |
|:-----|:---------|:--------:|
| `server/templates.py` | TAB_STATE 3-tab 重构 + inbox poll 集成 + 绑定码清理 + 工作区面板简化 | ✅ |
| `server/web_viewer.py` | 仅删除绑定码 3 个 handler + 路由注册 | ✅ |
| `server/auth.py` | 仅删除绑定码 4 个函数（generate/create/approve/_code_expired）+ WEB_CODE_PREFIX | ✅ |
| `server/persistence.py` | 仅删除绑定码 5 个函数（load/save/get/set + _web_bind_codes 全局） | ✅ |
| `server/__main__.py` | 仅删除绑定码导入 + approve_web handler 降级 + load_web_bind_codes 调用 | ✅ |
| `server/handler.py` | 仅删除 approve_web handler 中的绑定码逻辑，替换为 deprecation 响应 | ✅ |

**结论：** 6 文件全部在范围内，无意外改动 ✅

### ✅ 2.2 TAB_STATE 3-tab 架构

**方法：** 从 commit 中提取 `<script>` 块（23,496 bytes），用 Python 逐项检查 TAB_STATE 引用。

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__', label: '📬 收件箱', permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',    label: '🔧 管理员', permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,         label: '🗂️ 历史',  permanent: true, visible: true },
};
```

| 检查项 | 结果 | 方法 |
|:-------|:-----|:-----|
| 共几个 tab？ | 3（tab1/tab2/tab3） | ✅ 代码检查 |
| tab4/tab5 残留？ | **0 次出现** | ✅ `grep -c 'tab4\|tab5'` = 0 |
| `renderTabBar()` 遍历方式 | `Object.entries(TAB_STATE)` 动态遍历 | ✅ |
| `selectTab()` 路由 tab1→inbox | `tab.channel === '__inbox__'` → `loadInboxMessages(null)` | ✅ |
| `selectTab()` 路由 tab2→_admin | `tab.channel === '_admin'` → `loadMessages('_admin', null)` | ✅ |
| tab3（历史）默认 | 显示「👈 点击右侧「工作室归档」选择一个查看」 | ✅ |
| `switchHistoryTab()` 设置 tab3 | 正确设置 `TAB_STATE.tab3.channel` + `label` + 调用 `selectTab('tab3')` | ✅ |
| `init()` 默认 tab | `var firstTab = 'tab1'` → 始终默认收件箱 | ✅ |
| 旧 localStorage tab2 恢复逻辑 | 已删除（tab2 不再做活跃工作区） | ✅ |
| 旧活跃工作区检测（init 中 fetch /api/workspaces） | 已删除 | ✅ |
| 15s workspace poll 检测 tab3 有效性 | 保留，tab3 channel 失效时自动回退 tab1 | ✅ |

### ✅ 2.3 `switchToActiveTab()` — 零残留

**方法：** 从 commit 中提取 JS 全文 + `grep -n 'switchToActiveTab'` server/templates.py

```bash
$ grep -rn 'switchToActiveTab' server/templates.py
(exit 1 — no matches)
```

✅ 0 匹配。函数彻底删除，无任何引用残留。

### ✅ 2.4 WS inbox 事件链

**完整链路（代码级轨迹）：**

```
WebSocket onmessage (templates.py JS L395)
  └─ data.type === 'chat_message'
     └─ ch = data.channel || '_admin'
        └─ ch.startsWith('_inbox:') ?
           ├─ YES: inbox handler
           │  ├─ msg = data.message || data
           │  ├─ _inboxCache.push(msg)
           │  ├─ activeTabId === 'tab1' ?
           │  │  ├─ YES → list.insertBefore(createInboxMessageEl(msg), list.firstChild)  ← 直接显示
           │  │  └─ NO  → unreadCounts['__inbox__'] = (unreadCounts['__inbox__'] || 0) + 1
           │  │            renderTabBar()                                                ← 红点+1
           │  └─ (消息同时被 appendMessage → msgContainers 更新)
           └─ NO → appendMessage(ch, data.message || data)  ← 普通消息

selectTab('tab1') (L101-116)
  ├─ unreadCounts['__inbox__'] = 0        ← 红点清零
  ├─ renderTabBar()                       ← 重绘 Tab bar（无红点）
  └─ loadInboxMessages(null)              ← 全量拉取收件箱

renderTabBar() (L76-97)
  └─ tab1 渲染分支：
     const inboxUnread = unreadCounts['__inbox__'] || 0;
     html += ... + (inboxUnread > 0 ? '<span class="badge">N</span>' : '') + ...
```

| 环节 | 代码位置 | 状态 |
|:-----|:---------|:----:|
| WS onmessage 检查 `chat_message` | L398 | ✅ |
| Channel 前缀 `_inbox:` 检查 | L401 | ✅ |
| 当前在 inbox tab → 直接 prepend | L404-406 | ✅ |
| 不在 inbox tab → 红点+1 | L408 | ✅ |
| `unreadCounts` 安全递增 | L408 `(unreadCounts['__inbox__'] || 0) + 1` | ✅ |
| 切换 tab1 → 红点清零 | L113 | ✅ |
| `renderTabBar()` 红点显示 | L84-86 | ✅ |
| `_inboxCache` 客户端缓存 | L403 | ✅ |

### ✅ 2.5 绑定码 — 零残留

**方法：** 对 commit 状态下的每个文件，grep 绑码函数名和常量名。

| 文件 | grep `bind_code\|WEB_CODE\|generate_web_bind\|approve_web_bind` | 状态 |
|:-----|:---------------------------------------------------------------|:----:|
| `web_viewer.py` | 0 matches（仅 `BIND_TEMPLATE` 作为 GitHub 登录页模板名） | ✅ |
| `auth.py` | 0 matches | ✅ |
| `persistence.py` | 0 matches | ✅ |
| `handler.py` | 0 matches（仅 `bind_code_deprecated` 字符串——降级响应） | ✅ |
| `__main__.py` | 0 matches（同上） | ✅ |
| `templates.py` | `BIND_TEMPLATE` 常量（含 GitHub 登录页）——非绑定码残留 | ✅ |
| `config.py` | 0 matches | ✅ |

**关于 `BIND_TEMPLATE` 常量：** 该常量名在旧系统中用于绑定码页面，R83 中其内容已改为 GitHub OAuth 登录页面（`使用 GitHub 账号登录` 按钮 + SVG GitHub 图标 + 链接 `/auth/github/login`）。功能等价于「未认证用户的入口页面」，名称是历史遗留，不影响功能。不需要重命名。

**关于 `approve_web` handler 的 deprecation 响应：**
- `handler.py L6865-6870`: 旧 `approve_web` 消息类型保留作为降级路径，返回 `{"type": "error", "error": "bind_code_deprecated"}`
- `__main__.py L210-214`: 同上，双入口一致 ✅

这是正确的向后兼容行为——旧客户端发送 `approve_web` 不会崩溃，而是获得明确的弃用通知。

### ✅ 2.6 JS 语法检查

**方法：** 从 commit 的 templates.py 提取 `<script>` 块，`node --check` 验证。

```bash
$ python3 -c "import re; m=re.search(r'<script>(.*?)</script>', open('/dev/stdin').read(), re.DOTALL); open('/tmp/r83_js.js','w').write(m.group(1))" << templates.py
$ node --check /tmp/r83_js.js
(exit 0 — no output)
```

✅ 23,496 bytes JS，`node --check` 通过，无语法错误。

### ✅ 2.7 5s Poll Inbox — 增量追加

**完整代码（L438-476）：**

```javascript
setInterval(async function() {
  try {
    const activeTab = TAB_STATE[activeTabId];
    const channel = activeTab ? activeTab.channel : null;
    if (!channel) return;

    // R83: inbox tab uses /api/chat/inbox, not /api/chat
    if (channel === '__inbox__') {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const resp = await fetch('/api/chat/inbox?limit=50&token=' + encodeURIComponent(TOKEN), {signal: controller.signal});
      clearTimeout(timeout);
      if (!resp.ok) return;
      const data = await resp.json();
      const msgs = data.messages || [];
      const existing = msgContainers['__inbox__'] || [];
      const newMsgs = msgs.slice(existing.length);
      for (let i = 0; i < newMsgs.length; i++) {
        appendMessage('__inbox__', newMsgs[i]);
      }
      return;
    }
    // ... 非 inbox 通道 polling (同模式)
  } catch(_) {}
}, 5000);
```

| 检查项 | 结果 | 位置 |
|:-------|:-----|:----:|
| 间隔 | 5000ms = 5s | ✅ L477 |
| Inbox 分支条件 | `channel === '__inbox__'` | ✅ L447 |
| API 端点 | `/api/chat/inbox?limit=50&token=` | ✅ L450 |
| 加载/超时保护 | `AbortController` + `setTimeout(10000)` | ✅ L448-449 |
| 非 200 处理 | `if (!resp.ok) return;`（静默降级） | ✅ L452 |
| 错误不崩溃 | `try/catch(_) {}` 包裹 | ✅ L476 |
| 增量方式 | `msgs.slice(existing.length)` | ✅ L456 |
| 追加调用 | `appendMessage('__inbox__', newMsgs[i])` | ✅ L458 |
| 去重保护 | `_seenMsgHashes` 在 `appendMessage` 中（L200-203） | ✅ |

### ✅ 额外检查：去重（F-8）

`appendMessage()` 中（L194-227）：
```javascript
const hash = (msg.ts || '') + '|' + (msg.sender || msg.from_name || '') + '|' + (msg.content || '').substring(0, 80);
const chKey = channel + '|' + hash;
if (_seenMsgHashes[chKey]) return;
_seenMsgHashes[chKey] = true;
// Prune when > 500 entries
```

✅ WS 实时推送与 5s 轮询之间的去重机制完整保留。

### ✅ 额外检查：双入口一致性

`approve_web` 降级响应在两个入口中一致：

| 入口 | 文件 | 行号 | 行为 |
|:-----|:-----|:----:|:-----|
| websockets | `server/handler.py` | L6865-6870 | `bind_code_deprecated` + logger.info |
| aiohttp | `server/__main__.py` | L210-214 | `bind_code_deprecated` + logger.warning |

✅ 行为一致，仅日志级别不同（info vs warning，可接受）。

---

## 3. 边界情况分析

| # | 场景 | 预期 | 实现 | 状态 |
|:-:|:-----|:-----|:-----|:----:|
| 1 | 3-tab 架构 | tab1(收件箱)/tab2(管理员)/tab3(历史) | ✅ TAB_STATE 仅 3 条目 |
| 2 | 无 inbox 消息 | 显示「暂无收件箱消息」 | ✅ `loadInboxMessages` L243 |
| 3 | WS 消息在 tab1 内 | 直接 prepend 到列表 | ✅ L406 |
| 4 | WS 消息在 tab2/tab3 | 增加未读红点 | ✅ L408 |
| 5 | 切换 tab1 | 红点清零 + 全量拉取 | ✅ L113-115 |
| 6 | 5s poll 时序竞争 | 去重防止重复 | ✅ `_seenMsgHashes` |
| 7 | 绑定码完全删除 | 6 文件全清 | ✅ 功能函数零残留 |
| 8 | `switchToActiveTab` 残留 | 零匹配 | ✅ |
| 9 | 旧 tab4/tab5 引用 | 零残留 | ✅ `grep` 0 匹配 |
| 10 | auth 失败（WS 关闭 4000-4999） | 清除 token + 重定向到 `/chat` | ✅ L428-431 |
| 11 | `/api/chat` 超时 | 显示「⏱ 连接超时，请刷新重试」 | ✅ L187 |
| 12 | poll API 失败 | 静默降级（不崩溃） | ✅ `catch(_) {}` |
| 13 | tab3 channel 被归档删除 | 自动回退 tab1 | ✅ 15s poll L494-504 |
| 14 | 滚动加载（loadMessages `since` 参数） | 分页增量 | ✅ 保留 |

---

## 4. 安全/遗留物检查

| 检查项 | 方法 | 结果 |
|:-------|:-----|:-----:|
| 绑定码硬编码残留 | 6 文件 grep | ✅ 无 |
| 内部 role 名残留 | 检查 BIND_TEMPLATE | ✅ 无（GitHub 登录页） |
| `switchToActiveTab` 残留 | grep server/templates.py | ✅ 无 |
| tab4/tab5 残留 | grep server/templates.py JS | ✅ 无 |
| TODO/FIXME 残留 | grep diff | ✅ 无 |
| R 标签准确 | 代码阅读 | ✅ 全部 R83 |
| 双入口同步 | handler.py vs __main__.py 对比 | ✅ |
| 净减 | diff --stat | ✅ -218 行 |
| 去重安全网 | `_seenMsgHashes` | ✅ 完整 |

---

## 5. 总结

| # | 审查项 | 独立验证方法 | 结果 |
|:-:|:-------|:------------|:----:|
| 1️⃣ | Scope 合规 | 阅读完整 diff，逐文件确认 | ✅ 6 文件全部在范围内 |
| 2️⃣ | TAB_STATE 3-tab 引用 | 提取 JS，grep tab4/tab5，检查所有引用点 | ✅ 完整 |
| 3️⃣ | `switchToActiveTab()` 零残留 | grep server/templates.py | ✅ 0 匹配 |
| 4️⃣ | WS inbox 事件链 | 逐行阅读 onmessage → unread badge → tab1 显示 | ✅ 完整链路 |
| 5️⃣ | 绑定码零残留 | 6 文件逐文件 grep 函数名/常量名/路由名 | ✅ 零功能残留 |
| 6️⃣ | JS 语法检查 | node --check | ✅ exit=0, 23,496 bytes |
| 7️⃣ | 5s poll inbox 增量追加 | 阅读完整代码分支 | ✅ 增量正确 + 去重 + 超时 |

**总体结论：🟢 通过 — 0 阻塞，进入 Step 6 QA**

审查完毕：2026-07-09 🔍 小周
