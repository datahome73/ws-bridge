#!/usr/bin/env node
/**
 * ws-bridge 客户端 — ws-bot 的 WebSocket 常连后台进程
 *
 * 连接到 ws-bridge 服务器（云端），实现 bot-to-bot 通信。
 * 同步上游 hermes-ws-bridge/client 的协议升级。
 *
 * 协议：
 *   认证（携带 last_seen_ts） → 心跳 → 收广播 → ACK确认 → 写管道 → 读 stdin 发消息
 *
 * 功能：
 *   - P0: 离线消息补推（last_seen_ts 持久化到 ws_bridge_state.json）
 *   - ACK 确认 + 超时重发（最多 2 次）
 *   - 自动重连（指数退避）
 *   - 消息去重
 *   - 文件管道 + stdin 双通道
 *   - on_offline 回调报告
 *
 * R11 兼容：
 *   - delivery_status — 消息送达确认（P1.1）
 *   - member_changed — 成员状态变更通知（P2.2）
 *   - mentions / is_task — 广播消息元数据（P2.1）
 *
 * 管道协议：
 *   stdout: [MSG]fromName|fromAgent|base64content  → 入站消息
 *           [STATUS]key=val|key=val                → 状态推送
 *   stderr: [REPORT]text                            → 需要用户关注的事件
 *   stdin:  SEND|content                            → 发消息指令
 *           PING                                    → 心跳检查
 *           STATUS                                  → 返回状态
 *
 * 文件管道（作为 stdin 的替代，进程 fork 后使用）：
 *   .ws-bridge-write   → 写入指令
 *   ws_bridge_state.json → 持久化状态（last_msg_ts 等）
 */

"use strict";

const fs = require("fs");
const path = require("path");
const WebSocket = require("ws");

// ── 配置 ───────────────────────────────────────────────────────────

const SCRIPT_DIR = __dirname;

const CONFIG = {
  wsUrl: process.env.WS_BRIDGE_URL || "wss://ws-bridge.example.com/ws",
  appId: process.env.WS_BRIDGE_APP_ID || "hermes-agent",
  agentId: process.env.WS_BRIDGE_AGENT_ID || "",
  botName: process.env.WS_BRIDGE_BOT_NAME || "ws-bot",
  pingInterval: 25000,
  reconnectBaseDelay: 3000,
  reconnectMaxDelay: 30000,
  ackTimeout: 5000,        // 等待 ACK 超时 (ms)
  maxRetries: 2,            // 发送重试次数
};

// 文件管道
const PIPE_FILE = path.join(SCRIPT_DIR, ".ws-bridge-write");

// 状态持久化文件名（同步上游 client 的 ws_bridge_state.json）
const STATE_FILENAME = "ws_bridge_state.json";
const STATE_FILE = path.join(SCRIPT_DIR, STATE_FILENAME);

// ── 状态 ───────────────────────────────────────────────────────────

let ws = null;
let connected = false;
let authed = false;
let stopEvent = false;
let reconnectDelay = CONFIG.reconnectBaseDelay;
let heartbeatTimer = null;
let pairingCode = null;
let lastMsgTs = 0;          // P0: 最后收到消息时间戳

// file pipe watcher
let pipeWatcher = null;
let pipeLastSize = 0;

// 去重
const seenIds = new Set();
const SEEN_MAX = 500;

// ── 日志 ───────────────────────────────────────────────────────────

function ts() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function log(...args) {
  const line = `[ws-bridge ${ts()}] ${args.join(" ")}`;
  console.log(line);
}

function warn(...args) {
  const line = `[ws-bridge ${ts()}] ${args.join(" ")}`;
  console.warn(line);
}

function reportToUser(msg) {
  console.error(`[REPORT]${msg}`);
}

function saveBasicState() {
  const state = {
    connected,
    authed,
    pid: process.pid,
    ts: Date.now(),
    pairingCode,
  };
  try {
    const tmp = STATE_FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, STATE_FILE);
  } catch {}
}

// ── P0: last_msg_ts 持久化 ────────────────────────────────────────

/**
 * 加载持久化的 last_msg_ts（gateway 重启后仍能恢复断线前的消息偏移）。
 * 同步上游 client 的 _load_last_msg_ts。
 */
function loadLastMsgTs() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const data = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8"));
      return typeof data.last_msg_ts === "number" ? data.last_msg_ts : 0;
    }
  } catch (err) {
    warn(`loadLastMsgTs error: ${err.message}`);
  }
  return 0;
}

/**
 * 原子持久化 last_msg_ts（tmp 写入 + rename）。
 * 同步上游 client 的 _save_last_msg_ts。
 */
function saveLastMsgTs(ts) {
  try {
    const tmp = STATE_FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify({ last_msg_ts: ts }));
    fs.renameSync(tmp, STATE_FILE);
  } catch (err) {
    warn(`saveLastMsgTs error: ${err.message}`);
  }
}

// ── 网络 ───────────────────────────────────────────────────────────

async function connect() {
  if (stopEvent) return false;

  log(`Connecting to ${CONFIG.wsUrl}...`);

  // P0: 加载上次消息时间戳，携带给服务端做离线补推
  lastMsgTs = loadLastMsgTs();
  if (lastMsgTs > 0) {
    log(`Last seen timestamp: ${lastMsgTs}`);
  }

  return new Promise((resolve) => {
    try {
      ws = new WebSocket(CONFIG.wsUrl);
    } catch (err) {
      warn(`Connection failed: ${err.message}`);
      resolve(false);
      return;
    }

    const timeout = setTimeout(() => {
      warn("Connection timeout");
      try { ws.close(); } catch {}
      resolve(false);
    }, 10000);

    ws.on("open", () => {
      clearTimeout(timeout);
      log("WebSocket connected — sending auth...");

      const authPayload = {
        type: "auth",
        app_id: CONFIG.appId,
        agent_id: CONFIG.agentId,
        name: CONFIG.botName,
      };

      // P0: 带上 last_seen_ts 让服务端补推离线消息
      if (lastMsgTs > 0) {
        authPayload.last_seen_ts = lastMsgTs;
      }

      const authMsg = JSON.stringify(authPayload);

      try { ws.send(authMsg); } catch (err) {
        warn(`Auth send failed: ${err.message}`);
        resolve(false);
        return;
      }

      let authTimer = setTimeout(() => {
        warn("Auth timeout");
        try { ws.close(); } catch {}
        resolve(false);
      }, 10000);

      ws.once("message", (raw) => {
        clearTimeout(authTimer);
        try {
          const msg = JSON.parse(raw.toString());
          const type = msg.type || "";

          if (type === "auth_ok") {
            authed = true;
            connected = true;
            pairingCode = null;
            const role = msg.role || "member";
            log(`Auth OK — role=${role}, last_seen_ts=${lastMsgTs}`);
            reportToUser(`✅ 已接入 WS Bridge，身份: ${CONFIG.botName}（${role}）`);
            startHeartbeat();
            startReader();
            reconnectDelay = CONFIG.reconnectBaseDelay;
            saveBasicState();
            resolve(true);
          } else if (type === "auth_error") {
            const errMsg = msg.error || "unknown";
            warn(`Auth error: ${errMsg}`);
            reportToUser(`❌ 认证错误: ${errMsg}`);
            try { ws.close(); } catch {}
            resolve(false);
          } else if (type === "pairing_code") {
            pairingCode = msg.code || "???";
            warn(`配对码: ${pairingCode}`);
            saveBasicState();
            reportToUser(`🔑 新配对码: ${pairingCode}，需要管理员审批后重连`);
            try { ws.close(); } catch {}
            resolve(false);
          } else {
            warn(`Unexpected auth response: ${raw.toString().slice(0, 200)}`);
            try { ws.close(); } catch {}
            resolve(false);
          }
        } catch (err) {
          warn(`Auth parse error: ${err.message}`);
          try { ws.close(); } catch {}
          resolve(false);
        }
      });
    });

    ws.on("error", (err) => {
      clearTimeout(timeout);
      warn(`WebSocket error: ${err.message}`);
      resolve(false);
    });

    ws.on("close", () => {
      clearTimeout(timeout);
      if (connected) {
        log("Connection closed");
        connected = false;
        authed = false;
        stopHeartbeat();
        saveBasicState();
        if (!stopEvent) scheduleReconnect();
      }
    });
  });
}

function disconnect() {
  stopEvent = true;
  connected = false;
  authed = false;
  stopHeartbeat();
  stopPipeWatcher();
  pendingAcksClear();
  if (ws) {
    try { ws.close(); } catch {}
    ws = null;
  }
  saveBasicState();
  log("Disconnected");
}

function scheduleReconnect() {
  if (stopEvent) return;
  reconnectDelay = Math.min(reconnectDelay * 1.5, CONFIG.reconnectMaxDelay);
  const delay = reconnectDelay + Math.random() * 1000;  // jitter
  log(`Reconnecting in ${(delay / 1000).toFixed(0)}s...`);
  setTimeout(() => {
    if (!stopEvent) {
      connect().then((ok) => {
        if (ok) reconnectDelay = CONFIG.reconnectBaseDelay;
      });
    }
  }, delay);
}

// ── 心跳 ──────────────────────────────────────────────────────────

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: "ping" })); } catch {}
    }
  }, CONFIG.pingInterval);
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

// ── ACK 等待 ──────────────────────────────────────────────────────

// 存储等待 ACK 的 entries: msgId -> { resolve, reject, timeoutTimer, retryCount }
const pendingAcks = new Map();

function pendingAcksClear() {
  for (const entry of pendingAcks.values()) {
    clearTimeout(entry.timeoutTimer);
    entry.resolve(false);
  }
  pendingAcks.clear();
}

/**
 * 发送消息并等待 ACK，超时自动重试（最多 maxRetries 次）。
 * 同步上游 client 的 send_message 逻辑。
 */
function sendMessage(content, to = "*") {
  if (!ws || ws.readyState !== WebSocket.OPEN || !authed) {
    warn("Cannot send: not connected/authed");
    return false;
  }

  const msgId = `${CONFIG.agentId.slice(0, 12)}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const payload = {
    type: "message",
    content,
    to,
    from: CONFIG.agentId,
    from_name: CONFIG.botName,
    id: msgId,
    ts: Date.now() / 1000,
  };

  // 启动 ACK 等待循环（同步上游：send_message 内建 retry 循环）
  doSendAndWaitAck(msgId, payload, 0);

  return true;
}

function doSendAndWaitAck(msgId, payload, attempt) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !authed) {
    return;
  }

  // 发送
  try {
    ws.send(JSON.stringify(payload));
    const tag = attempt > 0 ? `RETRY ${payload.content.slice(0, 120)}` : payload.content.slice(0, 120);
    log(`>> ${tag} (id=${msgId.slice(0, 8)})`);
  } catch (err) {
    warn(`Send error: ${err.message}`);
    return;
  }

  // 注册超时等待
  if (pendingAcks.has(msgId)) {
    // 已有 entry，只需更新 timer
    const entry = pendingAcks.get(msgId);
    clearTimeout(entry.timeoutTimer);
    entry.timeoutTimer = setTimeout(() => {
      ackTimeoutHandler(msgId);
    }, CONFIG.ackTimeout);
    return;
  }

  const timeoutTimer = setTimeout(() => {
    ackTimeoutHandler(msgId);
  }, CONFIG.ackTimeout);

  pendingAcks.set(msgId, {
    resolve: (ok) => {},
    reject: () => {},
    timeoutTimer,
    retryCount: attempt,
    payload,
  });
}

function ackTimeoutHandler(msgId) {
  const entry = pendingAcks.get(msgId);
  if (!entry) return;

  if (entry.retryCount < CONFIG.maxRetries) {
    entry.retryCount++;
    warn(`No ACK for msg ${msgId.slice(0, 8)} (attempt ${entry.retryCount}/${CONFIG.maxRetries}), retrying...`);
    // 更新 payload 的 ts
    entry.payload.ts = Date.now() / 1000;
    doSendAndWaitAck(msgId, entry.payload, entry.retryCount);
  } else {
    warn(`Message ${msgId.slice(0, 8)} failed after ${CONFIG.maxRetries + 1} attempts`);
    pendingAcks.delete(msgId);
    reportToUser(`⚠️ 消息发送失败（重试 ${CONFIG.maxRetries + 1} 次后）：${entry.payload.content.slice(0, 80)}`);
  }
}

function handleAck(msg) {
  const ackId = msg.id || "";
  if (!ackId) return;
  const entry = pendingAcks.get(ackId);
  if (entry) {
    clearTimeout(entry.timeoutTimer);
    pendingAcks.delete(ackId);
    log(`ACK received for ${ackId.slice(0, 8)}`);
  }
}

// ── 消息读取 ──────────────────────────────────────────────────────

function startReader() {
  if (!ws) return;
  ws.removeAllListeners("message");
  ws.on("message", (raw) => {
    try {
      const msg = JSON.parse(raw.toString());
      handleMessage(msg);
    } catch (err) {
      warn(`Bad JSON: ${raw.toString().slice(0, 100)}`);
    }
  });
}

function handleMessage(msg) {
  const type = msg.type || "";

  if (type === "pong") return;

  if (type === "ack") {
    handleAck(msg);
    return;
  }

  if (type === "auth_ok") {
    authed = true;
    log(`Re-auth OK`);
    return;
  }

  if (type === "auth_error") {
    warn(`Auth error: ${msg.error || ""}`);
    reportToUser(`❌ 认证错误: ${msg.error}`);
    return;
  }

  if (type === "pairing_code") {
    pairingCode = msg.code || "???";
    warn(`重新配对: ${pairingCode}`);
    reportToUser(`🔑 新配对码: ${pairingCode}`);
    return;
  }

  if (type === "error") {
    warn(`Server error: ${msg.error || ""}`);
    return;
  }

  // R11 P1.1: 消息送达确认（管理员消息的 delivery report）
  if (type === "delivery_status") {
    const msgId = msg.id || "";
    const status = msg.status || {};
    const total = msg.total || 0;
    const delivered = msg.delivered || 0;
    log(`Delivery status for ${msgId.slice(0, 12)}: ${delivered}/${total} delivered`);
    for (const [name, s] of Object.entries(status)) {
      log(`  ${name}: ${s}`);
    }
    return;
  }

  // R11 P2.2: 成员状态变更通知
  if (type === "member_changed") {
    const wsId = msg.workspace_id || "?";
    const event = msg.event || "?";
    const memberName = msg.member_name || msg.target_agent_id || "?";
    const icon = event === "joined" ? "➕" : "➖";
    log(`${icon} ${memberName} ${event} workspace [${wsId}]`);
    // 透传给父进程
    const b64Content = Buffer.from(JSON.stringify({
      type: "member_changed",
      workspace_id: wsId,
      event,
      member_name: memberName,
    }), "utf-8").toString("base64");
    console.log(`[MSG]system|system|${b64Content}`);
    return;
  }

  // R11 P2.2: 工作区分配通知
  if (type === "workspace_assigned") {
    const wsId = msg.workspace_id || "?";
    log(`📋 Workspace assigned: ${wsId}`);
    return;
  }

  // P0: 离线消息补推（同步上游 _handle_message offline_messages 处理）
  if (type === "offline_messages") {
    const msgs = msg.messages || [];
    const count = msg.count || msgs.length;
    log(`Received ${count} offline messages via catchup`);
    reportToUser(`📥 离线补推 ${count} 条消息`);
    for (const m of msgs) {
      processBroadcast(m);
    }
    return;
  }

  if (type === "broadcast" || type === "message") {
    processBroadcast(msg);
    return;
  }

  log(`Unhandled: ${JSON.stringify(msg).slice(0, 100)}`);
}

function processBroadcast(msg) {
  const content = msg.content || "";
  const fromAgent = msg.from || msg.from_agent || "";
  const fromName = msg.from_name || (fromAgent ? fromAgent.slice(0, 20) : "unknown");
  const msgId = msg.id || "";
  const msgTs = msg.ts || 0;

  // R11 P2.1: Extract mentions / is_task metadata from broadcast
  const mentions = msg.mentions || msg.is_task_assignment || null;

  if (fromAgent === CONFIG.agentId || fromName === CONFIG.botName) return;

  if (!content && !msgId) return;

  // 去重（同步上游：在 broadcast/message 处理块中执行去重）
  if (msgId) {
    if (seenIds.has(msgId)) return;
    seenIds.add(msgId);
    if (seenIds.size > SEEN_MAX) seenIds.clear();
  }

  // P0: 更新 last_msg_ts 并持久化
  if (msgTs > lastMsgTs) {
    lastMsgTs = msgTs;
    saveLastMsgTs(lastMsgTs);
  }

  log(`<< [${fromName}] ${content.slice(0, 200)}`);

  // 通过 stdout 输出给父进程
  const b64Content = Buffer.from(content, "utf-8").toString("base64");
  // R11 P2.1: 附加 mentions 元数据（若存在）
  let meta = "";
  if (mentions) {
    meta = `|${JSON.stringify(mentions)}`;
  }
  console.log(`[MSG]${fromName}|${fromAgent}|${b64Content}${meta}`);
}

// ── 文件管道监听（父进程写入指令文件） ──────────────────────────

function startPipeWatcher() {
  stopPipeWatcher();
  if (!fs.existsSync(PIPE_FILE)) {
    fs.writeFileSync(PIPE_FILE, "");
  }
  pipeLastSize = fs.statSync(PIPE_FILE).size;

  pipeWatcher = fs.watch(PIPE_FILE, (eventType) => {
    if (eventType !== "change") return;
    try {
      const stats = fs.statSync(PIPE_FILE);
      if (stats.size <= pipeLastSize) return;

      const fd = fs.openSync(PIPE_FILE, "r");
      const buf = Buffer.alloc(stats.size - pipeLastSize);
      fs.readSync(fd, buf, 0, buf.length, pipeLastSize);
      fs.closeSync(fd);

      const newContent = buf.toString("utf-8");
      const lines = newContent.split("\n");

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        if (trimmed === "PING") {
          console.log("[STATUS]alive");
        } else if (trimmed === "STATUS") {
          console.log(`[STATUS]connected=${connected}|authed=${authed}|pid=${process.pid}|lastMsgTs=${lastMsgTs}`);
        } else if (trimmed.startsWith("SEND|")) {
          const content = trimmed.slice(5);
          sendMessage(content);
        }
      }

      pipeLastSize = stats.size;
    } catch (err) {
      // file may be gone briefly
    }
  });
}

function stopPipeWatcher() {
  if (pipeWatcher) {
    pipeWatcher.close();
    pipeWatcher = null;
  }
}

// ── stdin 监听 ────────────────────────────────────────────────────

function setupStdin() {
  process.stdin.setEncoding("utf-8");
  process.stdin.on("data", (chunk) => {
    const lines = chunk.toString().split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (trimmed === "PING") {
        console.log("[STATUS]alive");
      } else if (trimmed === "STATUS") {
        console.log(`[STATUS]connected=${connected}|authed=${authed}|pid=${process.pid}|lastMsgTs=${lastMsgTs}`);
      } else if (trimmed.startsWith("SEND|")) {
        const content = trimmed.slice(5);
        sendMessage(content);
      }
    }
  });
}

// ── 启动 ──────────────────────────────────────────────────────────

async function main() {
  log(`${CONFIG.botName} starting...`);
  log(`  Server: ${CONFIG.wsUrl}`);
  log(`  Agent:  ${CONFIG.agentId}`);

  // P0: 加载持久化的 lastMsgTs（从 ws_bridge_state.json）
  lastMsgTs = loadLastMsgTs();
  log(`  lastMsgTs: ${lastMsgTs}`);
  log(`  State file: ${STATE_FILE}`);

  // 监听 stdin（父进程直接通信）
  setupStdin();

  // 文件管道监听（也支持外部写文件）
  startPipeWatcher();

  // 初始状态
  saveBasicState();

  // 连接
  const ok = await connect();

  if (!ok) {
    log("Initial connect failed — will retry");
  }

  // 保持运行
  process.stdin.resume();
}

process.on("SIGINT", () => {
  log("SIGINT received");
  disconnect();
  process.exit(0);
});

process.on("SIGTERM", () => {
  log("SIGTERM received");
  disconnect();
  process.exit(0);
});

process.on("uncaughtException", (err) => {
  warn(`Uncaught: ${err.message}`);
  // don't exit, let reconnect handle
});

main().catch((err) => {
  warn(`Fatal: ${err.message}`);
  process.exit(1);
});
