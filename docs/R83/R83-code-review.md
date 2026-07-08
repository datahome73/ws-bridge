# R83 代码审查报告 — Web 端 Inbox 化改造 🌐

> **审查人：** 🔍 审查工程师
> **审查对象：** `2713383` feat(R83): Web 端 Inbox 化改造 — Tab 重设计 + 收件箱增强 + 绑定码清理
> **审查日期：** 2026-07-09
> **改动统计：** 6 文件, +85/-303 = **-218 行净删**

---

## 0. 审查结论

> 🟢 **通过 — 0 项 🔴, 0 项 🟡, 0 项 💡 — 直接进入 Step 5 QA**

---

## 1. 改动统计

| 文件 | + | - | 净 | 说明 |
|:-----|:-:|:-:|:--:|:-----|
| `server/templates.py` | +85 | -137 | **-52** | Tab 3-tab 重构 + inbox poll 集成 + 绑定码删除 |
| `server/web_viewer.py` | +0 | -63 | **-63** | 删除绑定码全套函数 |
| `server/auth.py` | +0 | -54 | **-54** | 删除绑定码全套函数 |
| `server/persistence.py` | +0 | -24 | **-24** | 删除绑定码存储 |
| `server/__main__.py` | +0 | -15 | **-15** | 删除绑定码启动 |
| `server/handler.py` | +0 | -10 | **-10** | 删除绑定码命令路由 |
| **合计** | **+85** | **-303** | **-218** | ✅ 净减 |

---

## 2. 逐项审查

### ✅ 2.1 Scope 合规

| 文件/模块 | 状态 |
|:----------|:-----|
| `server/templates.py` | ✅ 前端重构——正确 |
| `server/web_viewer.py` | ✅ 函数删除——正确 |
| `server/auth.py` | ✅ 函数删除——正确 |
| `server/persistence.py` | ✅ 数据层删除——正确 |
| `server/__main__.py` | ✅ 启动清理——正确 |
| `server/handler.py` | ✅ 仅删除绑定码命令路由——无不相关改动 |

**结论：** 6 文件全部在范围内，无意外改动 ✅

### ✅ 2.2 TAB_STATE 3-tab 架构

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__', label: '📬 收件箱', permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',    label: '🔧 管理员', permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,         label: '🗂️ 历史',  permanent: true, visible: true },
};
```

| 检查项 | 结果 |
|:-------|:-----|
| 共几个 tab？ | 3（tab1/tab2/tab3） |
| tab4/tab5 已删？ | ✅ 零残留 |
| `tab.:` 定义 | 3 处 ✅ |
| `selectTab()` 兼容 | ✅ tab1→inbox, tab2→_admin, tab3→历史 |
| `renderTabBar()` 遍历 | ✅ 遍历 `Object.entries(TAB_STATE)` |
| 活跃 tab 显示 | ✅ 活跃 Tab 高亮 |

### ✅ 2.3 `switchToActiveTab()` — 零残留

```bash
$ grep -rn 'switchToActiveTab' server/
# (no output, only __pycache__ binary)
```

✅ 0 匹配。函数已彻底删除。

### ✅ 2.4 WS inbox 事件链

**完整链路：**

```
WS onmessage (L528-542)
  ├─ data.type === 'chat_message'
  │  └─ ch.startsWith('_inbox:')
  │     ├─ msg = data.message || data
  │     ├─ _inboxCache.push(msg)
  │     ├─ activeTabId === 'tab1'?
  │     │  ├─ YES → list.insertBefore(msg, list.firstChild)   ← 直接显示
  │     │  └─ NO  → unreadCounts['__inbox__'] += 1            ← 未读红点+1
  │     │            renderTabBar()
  │     └─ (消息同时被 appendMessage 处理 → msgContainers 更新)
  │
selectTab('tab1') (L242-245)
  ├─ unreadCounts['__inbox__'] = 0           ← 清零
  ├─ renderTabBar()                          ← 重绘(无红点)
  └─ loadInboxMessages(null)                 ← 全量拉取

renderTabBar (L214-218)
  └─ inboxUnread = unreadCounts['__inbox__'] || 0
     └─ <span class="badge">N</span>          ← 红点显示
```

| 环节 | 实现 | 状态 |
|:-----|:-----|:----:|
| WS 收到 inbox 消息 | `_inbox:` → `ch.startsWith('_inbox:')` | ✅ |
| 当前在 inbox tab？ | `activeTabId === 'tab1'` | ✅ |
| 是 → 直接 prepend | `list.insertBefore(msg, list.firstChild)` | ✅ |
| 否 → 红点+1 | `unreadCounts['__inbox__'] += 1` | ✅ |
| 切换 tab1 时清零 | `unreadCounts['__inbox__'] = 0` | ✅ |
| 红点渲染 | `(inboxUnread > 0 ? '<span class="badge">'...` | ✅ |

### ✅ 2.5 绑定码 — 零残留

| 文件 | grep `bind_code\|pairing_code\|BIND_TEMPLATE` | 状态 |
|:-----|:----------------------------------------------|:----:|
| `web_viewer.py` | 0 matches | ✅ |
| `auth.py` | 0 matches | ✅ |
| `persistence.py` | 0 matches | ✅ |
| `handler.py` | 0 matches | ✅ |
| `__main__.py` | 0 matches | ✅ |
| `templates.py` | 0 matches | ✅ |
| `config.py` | 0 matches | ✅ |

**所有文件零残留 ✅**

### ✅ 2.6 JS 语法检查

```
$ node --check /tmp/r83_js.js
(exit 0 — no output)
```

✅ JS 语法通过。`<script>` 标签内 23,496 字符 JS 无语法错误。

### ✅ 2.7 5s Poll Inbox — 增量追加

```javascript
setInterval(async function() {
  const channel = TAB_STATE[activeTabId].channel;
  if (channel === '__inbox__') {
    const msgs = await fetch('/api/chat/inbox?limit=50...');
    const existing = msgContainers['__inbox__'] || [];
    const newMsgs = msgs.slice(existing.length);   // 增量
    for (let i = 0; i < newMsgs.length; i++) {
      appendMessage('__inbox__', newMsgs[i]);       // 追加
    }
    return;
  }
  // ...非 inbox 通道 polling (同模式)
}, 5000);
```

| 检查项 | 结果 |
|:-------|:-----|
| 间隔 | 5000ms = 5s ✅ |
| inbox 分支 | `channel === '__inbox__'` ✅ |
| API 端点 | `/api/chat/inbox?limit=50` ✅ |
| 增量方式 | `msgs.slice(existing.length)` ✅ |
| 追加调用 | `appendMessage('__inbox__', newMsgs[i])` ✅ |
| 非 inbox 通道 | `/api/chat?channel=...` 同模式 ✅ |
| 10s 超时保护 | `AbortController` + `setTimeout` ✅ |
| 错误不崩溃 | `try/catch(_) {}` ✅ |

**增量追加机制说明：** 
- `msgContainers[channel]` 通过 `appendMessage` 的 `unshift(msg)` 维护与 API 一致的 DESC 顺序
- `msgs.slice(existing.length)` 跳过已存在的消息数量
- 已被 `_seenMsgHashes` 保护的二级去重（防 WS push 与 poll 重复）

### ✅ 额外检查：去重安全网

```javascript
// F-8 Dedup: 同一消息不会因 WS push + Poll double-delivery 出现两次
const hash = (msg.ts || '') + '|' + (msg.sender || msg.from_name || '') + '|' + (msg.content || '').substring(0, 80);
const chKey = channel + '|' + hash;
if (_seenMsgHashes[chKey]) return;
```

✅ 确保 WS 实时推送与 5s 轮询不会重复显示消息。

---

## 3. 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| 3-tab 架构 | tab1(收件箱)/tab2(管理员)/tab3(历史) | ✅ |
| 无 inbox 消息 | 显示「暂无收件箱消息」 | ✅ `loadInboxMessages` 检查 |
| WS 消息在 tab1 内 | 直接 prepend 到列表 | ✅ |
| WS 消息在 tab2/tab3 | 增加未读红点 | ✅ |
| 切换 tab1 | 红点清零，全量拉取 | ✅ |
| 5s poll 时序竞争 | dedup 防止重复 | ✅ `_seenMsgHashes` |
| 绑定码完全删除 | 旧代码路径不残留 | ✅ 6 文件全清 |
| `switchToActiveTab` 残留 | 零匹配 | ✅ |
| 旧 tab4/tab5 引用 | 零残留 | ✅ TAB_STATE 仅 3 条目 |

---

## 4. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 绑定码硬编码残留 | ✅ 无 |
| 内部 role 名残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| R 标签准确 | ✅ 全部为 R83 |
| 净减 | ✅ -218 行 |

---

## 5. 总结

| 审查项 | 结果 |
|:-------|:-----|
| 1️⃣ Scope 合规 | ✅ 6 文件全部在范围内 |
| 2️⃣ TAB_STATE 3-tab 引用 | ✅ tab1(收件箱)/tab2(管理员)/tab3(历史) |
| 3️⃣ `switchToActiveTab()` 零残留 | ✅ |
| 4️⃣ WS inbox 事件链 | ✅ onmessage→未读红点→tab1 显示 |
| 5️⃣ 绑定码零残留 | ✅ web_viewer.py + auth.py 全清 |
| 6️⃣ JS 语法检查 | ✅ node --check exit=0 |
| 7️⃣ 5s poll inbox 增量追加 | ✅ 正确 |

---

> **总体：🟢 通过 — 0 阻塞，直接进入 Step 5 QA**
>
> 审查完毕：2026-07-09 🔍 审查工程师
