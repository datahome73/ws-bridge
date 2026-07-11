"""WS IM Web UI templates."""
import json

BIND_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌉 WS Bridge 聊天室</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh;}
@media (max-width:600px){body{font-size:16px;}input,button{font-size:16px;}}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px;max-width:420px;width:90%;text-align:center;}
h1{font-size:1.5rem;margin-bottom:8px;}
p{color:#8b949e;font-size:0.9rem;margin-bottom:24px;}

.github-btn{display:inline-flex;align-items:center;gap:8px;background:#24292f;color:#fff;border:1px solid #444d56;border-radius:6px;padding:10px 20px;text-decoration:none;font-size:0.9rem;transition:background 0.2s}
.github-btn:hover{background:#2b3137}
.github-btn svg{flex-shrink:0}
</style>
</head>
<body>
<div class="card">
<h1>🌉 WS Bridge 聊天室</h1>
<p>使用 GitHub 账号登录</p>
<a id="githubLoginBtn" class="github-btn" href="/auth/github/login">
  <svg width="18" height="18" viewBox="0 0 16 16" fill="#fff"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>
  <span>使用 GitHub 登录</span>
</a>
</div>
</body>
</html>"""

CHAT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSIM</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;}
@media (max-width:600px){body{font-size:15px;}.tab{padding:8px 10px;font-size:13px;}.search-bar{flex-wrap:wrap;}.search-bar input{max-width:100%;}.ws-panel{width:calc(100% - 32px);right:16px;}.ws-btn-label{display:none;}}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:8px 16px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10;}
.header h1{font-size:1.1rem;}
.header .viewer{font-size:0.8rem;color:#8b949e;}
.ws-list-btn{background:none;border:1px solid #30363d;border-radius:6px;padding:2px 6px;cursor:pointer;font-size:1rem;line-height:1;color:#8b949e;margin-right:6px;display:inline-flex;align-items:center;gap:2px;}
.ws-list-btn:hover{color:#c9d1d9;border-color:#8b949e;}
.ws-panel{display:none;position:absolute;right:16px;top:44px;background:#161b22;border:1px solid #30363d;border-radius:8px;max-height:400px;overflow-y:auto;width:280px;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,0.5);}
.ws-panel.open{display:block;}
.ws-panel .ws-item{padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;border-bottom:1px solid #30363d;font-size:0.85rem;}
.ws-panel .ws-item:hover{background:rgba(255,255,255,0.05);}
.ws-panel .ws-item:last-child{border-bottom:none;}
.ws-panel .ws-badge{font-size:0.7rem;padding:1px 6px;border-radius:4px;flex-shrink:0;}
.ws-panel .ws-active{color:#3fb950;border:1px solid #3fb95044;}
.ws-panel .ws-archived{color:#8b949e;border:1px solid #30363d;}
.ws-section-header{padding:6px 14px;font-size:0.75rem;border-bottom:1px solid #30363d;}
.ws-section-active{color:#3fb950;}
.ws-section-archived{color:#8b949e;}
.tab-bar{display:flex;gap:0;background:#161b22;border-bottom:1px solid #30363d;overflow-x:auto;-webkit-overflow-scrolling:touch;}
.tab{display:flex;align-items:center;gap:6px;padding:10px 18px;cursor:pointer;color:#888;border-bottom:2px solid transparent;transition:all 0.2s;white-space:nowrap;user-select:none;}
.tab:hover{color:#ccc;background:rgba(255,255,255,0.05);}
.tab.active{color:#fff;border-bottom-color:#4fc3f7;background:rgba(79,195,247,0.1);}
.tab.pending{color:#666;font-size:0.85rem;}
.tab.admin-tab{color:#f0a040;}
.tab.admin-tab.active{border-bottom-color:#f0a040;background:rgba(240,160,64,0.15);}
.badge{background:#e53935;color:#fff;font-size:11px;border-radius:10px;padding:1px 6px;min-width:16px;text-align:center;}
.msg-list{padding:12px 16px;max-width:800px;margin:0 auto;}
.msg{padding:10px 12px;margin-bottom:6px;border-radius:8px;background:#161b22;border:1px solid #30363d;}
.msg .meta{display:flex;align-items:center;gap:8px;margin-bottom:4px;}
.msg .ts{font-size:0.75rem;color:#8b949e;font-family:monospace;}
.msg .sender{font-size:0.85rem;font-weight:600;color:#58a6ff;}
.msg .sender.s-xiaoai{color:#ffd700;}
.msg .sender.s-xiaogu{color:#ff7b72;}
.msg .sender.s-xiaokai{color:#79c0ff;}
.msg .sender.s-aitai{color:#d2a8ff;}
.msg .sender.s-xiaozhou{color:#7ee787;}
.msg .sender.s-taixia{color:#ffa657;}
.msg .sender.s-unknown{color:#8b949e;}
.msg .content{font-size:0.95rem;line-height:1.5;word-break:break-word;user-select:text;-webkit-user-select:text;}
.msg .content,.msg-sender{user-select:text;-webkit-user-select:text;}
.empty{text-align:center;color:#8b949e;padding:40px;font-size:0.9rem;}
.live-badge{display:inline-block;font-size:0.7rem;color:#3fb950;border:1px solid #3fb95033;border-radius:4px;padding:2px 6px;}
.live-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#3fb950;margin-right:4px;animation:pulse 1.5s infinite;}
/* R8: message type visual distinction */
.msg.system{background:#0d1117;border-color:#21262d;font-size:0.85rem;text-align:center;color:#8b949e;}
.msg.system .meta{justify-content:center;}
.msg.admin{border-left:3px solid #ffd700;background:#161b22;}
.msg.bot{border-left:3px solid #30363d;background:#161b22;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
/* R8: status bar */
.status-item{display:inline-flex;align-items:center;gap:3px;margin:0 3px;cursor:default;}
.status-dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0;}
.status-dot.online{background:#3fb950;box-shadow:0 0 3px #3fb95088;}
.status-dot.offline{background:#8b949e;}
.status-item.online{color:#c9d1d9;}
.status-item.offline{color:#666;}
.status-item .offline-warn{color:#f0883e;font-size:0.7rem;}
</style>
</head>
<body>
<div class="header">
  <div style="display:flex;flex-direction:column;gap:2px;">
    <h1 style="margin:0;font-size:1.1rem;">WSIM</h1>
    <div><span class="live-badge"><span class="live-dot"></span>实时</span></div>
  </div>
  <div class="right-group" style="display:flex;align-items:center;gap:8px;">
    <button id="wsListBtn" class="ws-list-btn" title="工作室列表">📋 <span class="ws-btn-label">历史工作室</span></button>
    <button id="toggleSearchBtn" class="ws-list-btn" title="搜索" style="margin-right:0;">🔍</button>
    <div id="status-bar" style="font-size:0.75rem;color:#8b949e;"></div>
    <div class="viewer" id="viewerName">__VIEWER__</div>
    <button id="logoutBtn" style="font-size:0.7rem;cursor:pointer;background:none;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:2px 6px;margin-left:4px;">登出</button>
  </div>
</div>


<div class="search-bar" id="searchBar" style="display:none;">
  <input type="text" id="searchInput" placeholder="搜索当前频道消息…" style="flex:1;max-width:400px;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 10px;color:#c9d1d9;font-size:0.85rem;outline:none;">
  <button id="searchBtn" style="background:#21262d;border:1px solid #30363d;border-radius:6px;padding:6px 10px;color:#c9d1d9;cursor:pointer;font-size:0.8rem;">🔍</button>
  <button id="searchClearBtn" style="display:none;background:#21262d;border:1px solid #30363d;border-radius:6px;padding:6px 10px;color:#8b949e;cursor:pointer;font-size:0.8rem;">✕ 退出搜索</button>
</div>

<div class="tab-bar" id="tabBar"></div>

<div id="msgList" class="msg-list">
  <div class="empty">加载中...</div>
</div>

<script>
const TOKEN='__TOKEN__';

// ── R83: Tab state model — 3-tab (inbox | admin | history) ──
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__',    label: '📬 收件箱',   permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史',    permanent: true, visible: true },
};
let activeTabId = 'tab1';
let unreadCounts = { '__inbox__': 0 };
const msgContainers = {};
let searchMode = false;
// R38 / 🔧 F-8: Deduplicate messages from WS push + poll double-delivery
const _seenMsgHashes = {};
// R76: archive state
let archiveMode = false;
let lastArchiveTs = 0;
// R76: inbox client-side cache for WS push
let _inboxCache = [];

// ── Panel cache ──
let wsPanelCache = null;
let wsPanelCacheTime = 0;
const WS_PANEL_CACHE_TTL = 30000; // 30s

// ── Workspaces poll ──
let lastWorkspacesJson = '';

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function formatTime(tsNum) {
  if (typeof tsNum === 'number') {
    const d = new Date(tsNum * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today - 86400000);
    const msgDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const pad = (n) => String(n).padStart(2, '0');
    const time = pad(d.getHours()) + ':' + pad(d.getMinutes());
    if (msgDate.getTime() === today.getTime()) return '今天 ' + time;
    if (msgDate.getTime() === yesterday.getTime()) return '昨天 ' + time;
    return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + time;
  }
  return tsNum || '';
}

function formatClosedAt(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const pad = function(n) { return String(n).padStart(2, '0'); };
  return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai','爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia'};

function createMessageEl(m) {
  const div = document.createElement('div');
  const sender = m.from_name || m.name || m.sender || '';
  let typeClass = 'bot';
  if (sender === '系统' || m._workspace_event) {
    typeClass = 'system';
  } else if (sender === '小爱' || sender === 'admin') {
    typeClass = 'admin';
  }
  div.className = 'msg ' + typeClass;
  const cls = colorMap[sender] || 'unknown';
  div.innerHTML = '<div class="meta"><span class="ts">' + formatTime(m.ts) + '</span><span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span></div><div class="content">' + escapeHtml(m.content || '') + '</div>';
  return div;
}

// ── R20/R35/R38: Fixed 4-tab rendering (active | lobby | admin | history) ──

function renderTabBar() {
  const bar = document.getElementById('tabBar');
  let html = '';
  for (const [id, tab] of Object.entries(TAB_STATE)) {
    const isActive = activeTabId === id;
    if (id === 'tab1') {
      const inboxUnread = unreadCounts['__inbox__'] || 0;
      html += '<div class="tab' + (isActive ? ' active' : '') + '" data-tab="tab1" onclick="selectTab(\'tab1\')">📬 收件箱' +
        (inboxUnread > 0 ? '<span class="badge">' + inboxUnread + '</span>' : '') + '</div>';
    } else if (id === 'tab2') {
      html += '<div class="tab admin-tab' + (isActive ? ' active' : '') + '" data-tab="tab2" onclick="selectTab(\'tab2\')">' +
        tab.label + '</div>';
    } else {
      const tab3Class = 'tab' + (isActive ? ' active' : '') + (!tab.channel ? ' pending' : '');
      html += '<div class="' + tab3Class + '" data-tab="tab3" onclick="selectTab(\'tab3\')">' +
        (tab.channel ? tab.label : '🗂️ 历史') + '</div>';
    }
  }
  bar.innerHTML = html;
}

// ── R20: Tab selection ──

function selectTab(tabId) {
  if (tabId === activeTabId) return;
  if (searchMode) exitSearchMode();

  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  const tabEl = document.querySelector('.tab[data-tab="' + tabId + '"]');
  if (tabEl) tabEl.classList.add('active');

  activeTabId = tabId;

  // R83: inbox tab (tab1) — no input box, clear unread, load inbox messages
  if (tabId === 'tab1') {
    unreadCounts['__inbox__'] = 0;
    renderTabBar();
    document.getElementById('inputArea').style.display = 'none';
    loadInboxMessages(archiveMode ? lastArchiveTs : null);
    return;
  }

  // R83: admin tab (tab2) — no input box
  if (tabId === 'tab2') {
    document.getElementById('inputArea').style.display = 'none';
    const tab = TAB_STATE[tabId];
    if (tab && tab.channel) {
      loadMessages(tab.channel, archiveMode ? lastArchiveTs : null);
    }
    return;
  }

  const tab = TAB_STATE[tabId];
  if (tab && tab.channel) {
    loadMessages(tab.channel, archiveMode ? lastArchiveTs : null);
  } else if (tabId === 'tab3') {
    document.getElementById('msgList').innerHTML = '<div class="empty">👈 点击右侧「历史工作室」选择一个查看</div>';
  }
}

function switchHistoryTab(wsId, wsName) {
  TAB_STATE.tab3.channel = wsId;
  TAB_STATE.tab3.label = '🗂️ ' + wsName;
  if (!(wsId in unreadCounts)) unreadCounts[wsId] = 0;
  if (!(wsId in msgContainers)) msgContainers[wsId] = [];
  renderTabBar();
  selectTab('tab3');
  // R76: load archive full-channel history if workspace is archived
  loadArchiveMessages(wsId);
}

async function loadMessages(channel, since) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    let url = '/api/chat?channel=' + encodeURIComponent(channel) + '&limit=50&token=' + encodeURIComponent(TOKEN);
    if (since) url += '&since=' + since;
    const resp = await fetch(url, {signal: controller.signal});
    clearTimeout(timeout);
    if (!resp.ok) {
      // R33: token expired → clear and redirect to bind page
      if (resp.status === 401) {
        try { localStorage.removeItem('ws_bridge_token'); } catch(e) {}
        location.href = '/chat';
        return;
      }
      list.innerHTML = '<div class="empty">加载失败（请刷新重试）</div>'; return; }
    const data = await resp.json();
    const msgs = data.messages || [];
    list.innerHTML = '';
    if (msgs.length === 0) {
      list.innerHTML = '<div class="empty">暂无消息</div>';
      msgContainers[channel] = [];
      return;
    }
    // 🔧 Explicit sort: newest first (insurance against any ordering issue)
    msgs.sort(function(a, b) {
      var ta = a.ts || 0, tb = b.ts || 0;
      if (typeof ta === 'string') ta = ta.split(':').reduce(function(s,v){return Number(s)*60+Number(v);});
      if (typeof tb === 'string') tb = tb.split(':').reduce(function(s,v){return Number(s)*60+Number(v);});
      return tb - ta;
    });
    msgContainers[channel] = msgs;
    for (let i = 0; i < msgs.length; i++) {
      // 🔧 F-8: Dedup by content hash (shared _seenMsgHashes with appendMessage)
      const hash = (msgs[i].ts || '') + '|' + (msgs[i].sender || msgs[i].from_name || '') + '|' + (msgs[i].content || '').substring(0, 80);
      const chKey = channel + '|' + hash;
      if (_seenMsgHashes[chKey]) continue;
      _seenMsgHashes[chKey] = true;
      const el = createMessageEl(msgs[i]);
      el.classList.add('new-msg');
      list.appendChild(el);
    }
  } catch(e) {
    clearTimeout(timeout);
    if (e.name === 'AbortError') {
      list.innerHTML = '<div class="empty">⏱ 连接超时，请刷新重试</div>';
    } else {
      list.innerHTML = '<div class="empty">加载失败（网络异常）</div>';
    }
  }
}

function appendMessage(channel, msg) {
  // Get current channel from active tab state
  const activeTab = TAB_STATE[activeTabId];
  const currentCh = activeTab ? activeTab.channel : null;

  // 🔧 F-8: Dedup by content hash (WS push may arrive alongside poll refresh)
  const hash = (msg.ts || '') + '|' + (msg.sender || msg.from_name || '') + '|' + (msg.content || '').substring(0, 80);
  const chKey = channel + '|' + hash;
  if (_seenMsgHashes[chKey]) return;
  _seenMsgHashes[chKey] = true;
  // Prune hash map if too large
  if (Object.keys(_seenMsgHashes).length > 500) {
    const keys = Object.keys(_seenMsgHashes);
    for (let i = 0; i < 200; i++) delete _seenMsgHashes[keys[i]];
  }

  if (channel !== currentCh) {
    unreadCounts[channel] = (unreadCounts[channel] || 0) + 1;
    return;
  }
  const list = document.getElementById('msgList');
  const empty = list.querySelector('.empty');
  if (empty) empty.remove();
  if (msgContainers[channel]) {
    msgContainers[channel].unshift(msg);
  }
  const el = createMessageEl(msg);
  el.classList.add('new-msg');
  if (list.firstChild) {
    list.insertBefore(el, list.firstChild);
  } else {
    list.appendChild(el);
  }
}

// ── R76: Inbox message loading ────────────────────────────────────────

async function loadInboxMessages(since) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  let url = '/api/chat/inbox?limit=50&token=' + encodeURIComponent(TOKEN);
  if (since) url += '&since=' + since;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('fetch failed');
    const data = await resp.json();
    const msgs = data.messages || [];
    list.innerHTML = '';
    if (msgs.length === 0) {
      list.innerHTML = '<div class="empty">暂无收件箱消息</div>';
      return;
    }
    for (const m of msgs) {
      list.appendChild(createInboxMessageEl(m));
    }
  } catch(e) {
    list.innerHTML = '<div class="empty">加载失败</div>';
  }
}

function createInboxMessageEl(m) {
  const div = document.createElement('div');
  div.className = 'msg bot';
  const sender = m.from_name || m.from || m.sender || '?';
  const receiver = m.to_name || '?';
  const cls = colorMap[sender] || 'unknown';
  div.innerHTML =
    '<div class="meta">' +
      '<span class="ts">' + formatTime(m.ts) + '</span>' +
      '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>' +
      '<span style="color:#8b949e;margin:0 4px;">→</span>' +
      '<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>' +
    '</div>' +
    '<div class="content">' + escapeHtml(m.content || '') + '</div>';
  return div;
}

// ── R76: Archive message loading (full channel history) ───────────────

async function loadArchiveMessages(wsId) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  const resp = await fetch('/api/chat/archive?workspace_id=' + encodeURIComponent(wsId) + '&token=' + encodeURIComponent(TOKEN));
  if (!resp.ok) { list.innerHTML = '<div class="empty">加载失败</div>'; return; }
  const data = await resp.json();
  const msgs = data.messages || [];
  list.innerHTML = '';
  // Header showing workspace info
  const header = document.createElement('div');
  header.style.cssText = 'padding:8px 12px;margin-bottom:8px;border-radius:8px;background:#161b22;border:1px solid #30363d;font-size:0.8rem;color:#8b949e;';
  header.textContent = '📦 ' + data.workspace + ' · ' + msgs.length + ' 条消息 · ' + new Date(data.period.start * 1000).toLocaleString() + ' → ' + new Date(data.period.end * 1000).toLocaleString();
  list.appendChild(header);
  for (const m of msgs) {
    const el = createArchiveMessageEl(m);
    list.appendChild(el);
  }
}

function createArchiveMessageEl(m) {
  const div = document.createElement('div');
  div.className = 'msg bot';
  const sender = m.from_name || '';
  const label = m._channel_label || m.channel || '';
  const cls = colorMap[sender] || 'unknown';
  let inner = '<div class="meta"><span class="ts">' + formatTime(m.ts) + '</span>' +
    '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>';
  if (m.to_name) {
    inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
      '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
  }
  inner += '<span style="margin-left:auto;font-size:0.7rem;color:#8b949e;border:1px solid #30363d;border-radius:3px;padding:1px 4px;">' + escapeHtml(label) + '</span>';
  inner += '</div><div class="content">' + escapeHtml(m.content || '') + '</div>';
  div.innerHTML = inner;
  return div;
}

// ── R20: Workspace panel — partitioned + closed_at + desc sorted ──

function buildWsItem(w) {
  const badge = w.state === 'active' ? '🟢' : '🗂️';
  const cls = w.state === 'active' ? 'ws-active' : 'ws-archived';
  var clickAction;
  if (w.state === 'active') {
    const safeName = escapeHtml(w.name).replace(/'/g, "\\'");
    clickAction = "switchHistoryTab('" + w.id + "','" + safeName + "')";
  } else {
    const safeName = escapeHtml(w.name).replace(/'/g, "\\'");
    clickAction = "switchHistoryTab('" + w.id + "','" + safeName + "')";
  }
  var timeStr = '';
  if (w.state === 'archived' && w.closed_at) {
    timeStr = '<span style="margin-left:auto;color:#8b949e;font-size:0.65rem;">' + formatClosedAt(w.closed_at) + '</span>';
  }
  return '<div class="ws-item" onclick="' + clickAction + '; document.getElementById(\'wsPanel\').classList.remove(\'open\')">' +
    '<span class="ws-badge ' + cls + '">' + badge + '</span>' +
    '<span style="flex:1;">' + escapeHtml(w.name) + '</span>' +
    timeStr + '</div>';
}

async function renderWsPanel() {
  const wsPanel = document.getElementById('wsPanel');
  // Check cache
  var now = Date.now();
  if (wsPanelCache && (now - wsPanelCacheTime) < WS_PANEL_CACHE_TTL) {
    wsPanel.innerHTML = wsPanelCache;
    return;
  }
  try {
    const resp = await fetch('/api/workspaces');
    const data = await resp.json();
    const workspaces = data.workspaces || [];

    const activeWs = workspaces.filter(function(w) { return w.state === 'active'; });
    const archivedWs = workspaces.filter(function(w) { return w.state === 'archived'; });
    archivedWs.sort(function(a, b) { return (b.closed_at || 0) - (a.closed_at || 0); });

    var html = '';
    if (activeWs.length > 0) {
      html += '<div class="ws-section-header ws-section-active">🟢 活跃工作室</div>';
      html += activeWs.map(buildWsItem).join('');
    }
    if (archivedWs.length > 0) {
      html += '<div class="ws-section-header ws-section-archived">🗂️ 历史工作室</div>';
      html += archivedWs.map(buildWsItem).join('');
    }
    html = html || '<div style="padding:14px;color:#8b949e;font-size:0.85rem;">暂无工作室</div>';

    wsPanelCache = html;
    wsPanelCacheTime = Date.now();
    wsPanel.innerHTML = html;
  } catch(e) {
    wsPanel.innerHTML = '<div style="padding:14px;color:#8b949e;font-size:0.85rem;">加载失败</div>';
  }
}



// ── Initialization ──

async function init() {
  // R83: 默认收件箱 tab，no tab2 restore

  // R76: load archive state from /api/channels
  try {
    const chResp = await fetch('/api/channels?token=' + encodeURIComponent(TOKEN));
    if (chResp.ok) {
      const chData = await chResp.json();
      if (chData.archive_state) {
        archiveMode = !chData.archive_state.active;
        lastArchiveTs = chData.archive_state.last_archive_ts || 0;
      }
    }
  } catch(e) {}

  // 1. Render tab bar (fixed slots, no fetch needed)
  renderTabBar();

  // R83: 默认打开收件箱 tab
  var firstTab = 'tab1';
  selectTab(firstTab);

  // 3. Poll-based live updates (R101: replaced WS push with 5s polling)
  // ── Per-tab since tracking ──
  let lastTsByChannel = {};

  async function pollActiveChannel() {
    const activeTab = TAB_STATE[activeTabId];
    let channel = activeTab ? activeTab.channel : null;
    let endpoint, url;

    if (activeTabId === 'tab1') {
      // Inbox tab — use /api/chat/inbox
      endpoint = '/api/chat/inbox?limit=50&token=' + encodeURIComponent(TOKEN);
      const since = lastTsByChannel['__inbox__'] || 0;
      if (since > 0) endpoint += '&since=' + since;
    } else if (channel) {
      endpoint = '/api/chat?channel=' + encodeURIComponent(channel) + '&limit=50&token=' + encodeURIComponent(TOKEN);
      const since = lastTsByChannel[channel] || 0;
      if (since > 0) endpoint += '&since=' + since;
    } else {
      return;
    }

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const resp = await fetch(endpoint, {signal: controller.signal});
      clearTimeout(timeout);
      if (!resp.ok) return;
      const data = await resp.json();
      const msgs = data.messages || [];

      if (activeTabId === 'tab1') {
        // Inbox tab: display with createInboxMessageEl
        for (const m of msgs) {
          if (m.ts && m.ts > (lastTsByChannel['__inbox__'] || 0)) {
            lastTsByChannel['__inbox__'] = m.ts;
          }
          const list = document.getElementById('msgList');
          const empty = list.querySelector('.empty');
          if (empty) empty.remove();
          list.insertBefore(createInboxMessageEl(m), list.firstChild);
        }
      } else if (channel) {
        for (const m of msgs) {
          if (m.ts && m.ts > (lastTsByChannel[channel] || 0)) {
            lastTsByChannel[channel] = m.ts;
          }
          appendMessage(channel, m);
        }
      }
    } catch(_) {}
  }

  // Initial poll + every 5 seconds
  setTimeout(pollActiveChannel, 500);
  setInterval(pollActiveChannel, 5000);

  // Touch pull-to-refresh
  let touchStartY = 0;
  document.addEventListener('touchstart', function(e) { touchStartY = e.touches[0].clientY; });
  document.addEventListener('touchend', function(e) {
    const dy = e.changedTouches[0].clientY - touchStartY;
    if (dy > 100) pollActiveChannel();
  });

  // 4. R83: Poll workspaces — refresh panel cache + detect history tab changes
  setInterval(async function() {
    try {
      const resp = await fetch('/api/workspaces');
      const data = await resp.json();
      const workspaces = data.workspaces || [];
      const wsJson = JSON.stringify(workspaces);
      if (wsJson === lastWorkspacesJson) return;
      lastWorkspacesJson = wsJson;

      // Invalidate panel cache so next open re-fetches
      wsPanelCache = null;

      // Check if Tab3's channel still exists
      if (TAB_STATE.tab3.channel) {
        var exists = workspaces.some(function(w) { return w.id === TAB_STATE.tab3.channel; });
        if (!exists) {
          TAB_STATE.tab3.channel = null;
          TAB_STATE.tab3.label = '🗂️ 历史';
          if (activeTabId === 'tab3') {
            selectTab('tab1');  // 自动回退到收件箱
          } else {
            renderTabBar();
          }
        }
      }
    } catch(_) {}
  }, 15000);

  // 5. R8: Poll bot status
  let offlineSince = {};
  async function pollStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      const bar = document.getElementById('status-bar');
      const now = Date.now();
      if (data.agents) {
        data.agents.forEach(function(a) {
          if (!a.online) {
            if (!offlineSince[a.id]) offlineSince[a.id] = now;
          } else {
            delete offlineSince[a.id];
          }
        });
        bar.innerHTML = data.agents.map(function(a) {
          if (a.online) {
            const uptime = formatUptime(a.uptime_secs || 0);
            return '<span class="status-item online" title="在线 ' + uptime + '">' +
              '<span class="status-dot online"></span>' + escapeHtml(a.name) + '</span>';
          } else {
            const since = offlineSince[a.id];
            const mins = since ? Math.floor((now - since) / 60000) : 0;
            const warn = mins >= 5 ? '<span class="offline-warn">⚠️</span>' : '';
            return '<span class="status-item offline" title="离线' + (mins > 0 ? ' ' + mins + '分钟' : '') + '">' +
              '<span class="status-dot offline"></span>' + escapeHtml(a.name) + warn + '</span>';
          }
        }).join('');
      }
    } catch(e) {}
  }
  function formatUptime(secs) {
    if (secs < 60) return secs + 's';
    if (secs < 3600) return Math.floor(secs / 60) + 'm';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return h + 'h ' + m + 'm';
  }
  setInterval(pollStatus, 15000);
  pollStatus();

  // 6. R20: Workspace list panel
  const wsPanel = document.createElement('div');
  wsPanel.className = 'ws-panel';
  wsPanel.id = 'wsPanel';
  document.body.appendChild(wsPanel);

  document.getElementById('wsListBtn').addEventListener('click', async function(e) {
    e.stopPropagation();
    if (wsPanel.classList.contains('open')) {
      wsPanel.classList.remove('open');
      return;
    }
    await renderWsPanel();
    wsPanel.classList.add('open');
  });

  // Close panel when clicking outside
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#wsPanel') && !e.target.closest('#wsListBtn')) {
      wsPanel.classList.remove('open');
    }
  });

  // 7. R8: Search toggle
  document.getElementById('toggleSearchBtn').addEventListener('click', function() {
    const bar = document.getElementById('searchBar');
    if (searchMode) {
      exitSearchMode();
    } else {
      bar.style.display = 'flex';
      searchMode = true;
      document.getElementById('searchInput').focus();
    }
  });

  function exitSearchMode() {
    searchMode = false;
    document.getElementById('searchBar').style.display = 'none';
    document.getElementById('searchInput').value = '';
    document.getElementById('searchClearBtn').style.display = 'none';
    document.getElementById('searchBtn').style.display = 'inline';
    const activeTab = TAB_STATE[activeTabId];
    if (activeTab && activeTab.channel) {
      loadMessages(activeTab.channel);
    }
  }

  async function doSearch() {
    const q = document.getElementById('searchInput').value.trim();
    if (!q) return;
    const activeTab = TAB_STATE[activeTabId];
    const channel = activeTab ? activeTab.channel : '';
    const resp = await fetch('/api/chat/search?q=' + encodeURIComponent(q) + '&channel=' + encodeURIComponent(channel) + '&token=' + encodeURIComponent(TOKEN));
    const data = await resp.json();
    const results = data.results || [];
    const list = document.getElementById('msgList');
    if (results.length === 0) {
      list.innerHTML = '<div class=\"empty\">未找到匹配的消息</div>';
    } else {
      list.innerHTML = '';
      results.forEach(function(m) {
        const el = createMessageEl(m);
        list.appendChild(el);
      });
    }
    document.getElementById('searchClearBtn').style.display = 'inline';
    document.getElementById('searchBtn').style.display = 'none';
  }

  document.getElementById('searchInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doSearch();
  });
  document.getElementById('searchBtn').addEventListener('click', doSearch);
  document.getElementById('searchClearBtn').addEventListener('click', exitSearchMode);

  // 8. R8: Logout button
  document.getElementById('logoutBtn').addEventListener('click', async function() {
    await fetch('/api/logout', {method: 'POST'});
    window.location.href = '/chat';
  });
}

init();
</script>
</body>
</html>"""
