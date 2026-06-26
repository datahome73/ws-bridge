#!/usr/bin/env node
/**
 * ws-bridge 客户端 — R19 多环境连接版
 *
 * 支持 WS_BRIDGE_URLS（env:url,env:url）多环境连接，
 * 向后兼容 WS_BRIDGE_URL（单连接）。
 *
 * 管道协议升级：
 *   SEND|content             → 发到默认环境（首个 URL 对应的 env）
 *   SEND|_target_env=xxx|content → 发到指定环境
 *
 * 收到的消息带 _source_env 标注来源环境。
 */

"use strict";

const fs = require("fs");
const path = require("path");
const WebSocket = require("ws");

// ── 配置 ───────────────────────────────────────────────────────────

const SCRIPT_DIR = __dirname;

// 解析 WS_BRIDGE_URLS：env:url,env:url
// 兼容 WS_BRIDGE_URL（旧格式，单连接，env 取 "default"）
const urlsStr = process.env.WS_BRIDGE_URLS || "";
const urlConns = urlsStr
  ? urlsStr.split(",").map((s) => {
      const idx = s.indexOf(":");
      return { env: s.slice(0, idx), url: s.slice(idx + 1) };
    })
  : process.env.WS_BRIDGE_URL
    ? [{ env: "default", url: process.env.WS_BRIDGE_URL }]
    : [{ env: "default", url: "wss://wsim.datahome73.cloud/ws" }];

const DEFAULT_ENV = urlConns[0].env;

const CONFIG = {
  appId: process.env.WS_BRIDGE_APP_ID || "298621237",
  agentId: process.env.WS_BRIDGE_AGENT_ID || "01KVHNXWE1KKJKMZ8A89TEHF1A",
  botName: process.env.WS_BRIDGE_BOT_NAME || "泰虾",
  pingInterval: 25000,
  reconnectBaseDelay: 3000,
  reconnectMaxDelay: 30000,
  ackTimeout: 10000,
  maxRetries: 0,
};

// 文件管道
const PIPE_FILE = path.join(SCRIPT_DIR, ".ws-bridge-write");

// ── 多连接状态 ─────────────────────────────────────────────────────

// 每个 env 一个连接对象
const conns = new Map(); // env -> { ws, connected, authed, lastMsgTs, heartbeatTimer, reconnectDelay, stopEvent }

function createConnState(env, url) {
  return {
    env,
    url,
    ws: null,
    connected: false,
    authed: false,
    stopEvent: false,
    lastMsgTs: 0,
    heartbeatTimer: null,
    reconnectDelay: CONFIG.reconnectBaseDelay,
  };
}

// 去重（全局共享）
const seenIds = new Set();
const SEEN_MAX = 500;

// 等待 ACK 的 entries（全局共享 msgId 空间）
const pendingAcks = new Map();

// ── 日志 ───────────────────────────────────────────────────────────

function ts() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function log(...args) {
  console.log(`[ws-bridge ${ts()}] ${args.join(" ")}`);
}

function warn(...args) {
  console.warn(`[ws-bridge ${ts()}] ${args.join(" ")}`);
}

function reportToUser(msg) {
  console.error(`[REPORT]${msg}`);
}

function stateFileForEnv(env) {
  return path.join(SCRIPT_DIR, `ws_bridge_state_${env}.json`);
}

function saveBasicState(conn) {
  const state = {
    connected: conn.connected,
    authed: conn.authed,
    pid: process.pid,
    ts: Date.now(),
    env: conn.env,
  };
  try {
    const file = stateFileForEnv(conn.env);
    const tmp = file + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, file);
  } catch {}
}

function loadLastMsgTs(env) {
  try {
    const file = stateFileForEnv(env);
    if (fs.existsSync(file)) {
      const data = JSON.parse(fs.readFileSync(file, "utf-8"));
      return typeof data.last_msg_ts === "number" ? data.last_msg_ts : 0;
    }
  } catch {}
  return 0;
}

function saveLastMsgTs(env, ts) {
  try {
    const file = stateFileForEnv(env);
    const tmp = file + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify({ last_msg_ts: ts }));
    fs.renameSync(tmp, file);
  } catch {}
}

// ── 单连接管理 ─────────────────────────────────────────────────────

function startHeartbeat(conn) {
  stopHeartbeat(conn);
  conn.heartbeatTimer = setInterval(() => {
    if (conn.ws && conn.ws.readyState === WebSocket.OPEN) {
      try { conn.ws.send(JSON.stringify({ type: "ping" })); } catch {}
    }
  }, CONFIG.pingInterval);
}

function stopHeartbeat(conn) {
  if (conn.heartbeatTimer) {
    clearInterval(conn.heartbeatTimer);
    conn.heartbeatTimer = null;
  }
}

function connectOne(conn) {
  if (conn.stopEvent) return;
  log(`[${conn.env}] Connecting to ${conn.url}...`);

  return new Promise((resolve) => {
    try {
      conn.ws = new WebSocket(conn.url);
    } catch (err) {
      warn(`[${conn.env}] Connection failed: ${err.message}`);
      resolve(false);
      return;
    }

    const timeout = setTimeout(() => {
      warn(`[${conn.env}] Connection timeout`);
      try { conn.ws.close(); } catch {}
      resolve(false);
    }, 10000);

    conn.ws.on("open", () => {
      clearTimeout(timeout);
      log(`[${conn.env}] WebSocket connected — sending auth...`);

      const authPayload = {
        type: "auth",
        app_id: CONFIG.appId,
        agent_id: CONFIG.agentId,
        name: CONFIG.botName,
      };
      // P0: 离线补推
      conn.lastMsgTs = loadLastMsgTs(conn.env);
      if (conn.lastMsgTs > 0) {
        authPayload.last_seen_ts = conn.lastMsgTs;
      }

      try { conn.ws.send(JSON.stringify(authPayload)); } catch (err) {
        warn(`[${conn.env}] Auth send failed: ${err.message}`);
        resolve(false);
        return;
      }

      let authTimer = setTimeout(() => {
        warn(`[${conn.env}] Auth timeout`);
        try { conn.ws.close(); } catch {}
        resolve(false);
      }, 10000);

      conn.ws.once("message", (raw) => {
        clearTimeout(authTimer);
        try {
          const msg = JSON.parse(raw.toString());
          const type = msg.type || "";

          if (type === "auth_ok") {
            conn.authed = true;
            conn.connected = true;
            const role = msg.role || "member";
            log(`[${conn.env}] Auth OK — role=${role}`);
            if (urlConns.length === 1) {
              reportToUser(`✅ 已接入 WS Bridge（${conn.env}），身份: ${CONFIG.botName}（${role}）`);
            }
            startHeartbeat(conn);
            setupReader(conn);
            conn.reconnectDelay = CONFIG.reconnectBaseDelay;
            saveBasicState(conn);
            resolve(true);
          } else if (type === "auth_error") {
            warn(`[${conn.env}] Auth error: ${msg.error || ""}`);
            reportToUser(`❌ 认证错误（${conn.env}）: ${msg.error}`);
            try { conn.ws.close(); } catch {}
            resolve(false);
          } else if (type === "pairing_code") {
            const code = msg.code || "???";
            warn(`[${conn.env}] 配对码: ${code}`);
            reportToUser(`🔑 配对码（${conn.env}）: ${code}，需管理员审批`);
            try { conn.ws.close(); } catch {}
            resolve(false);
          } else {
            warn(`[${conn.env}] Unexpected auth response: ${raw.toString().slice(0, 200)}`);
            try { conn.ws.close(); } catch {}
            resolve(false);
          }
        } catch (err) {
          warn(`[${conn.env}] Auth parse error: ${err.message}`);
          try { conn.ws.close(); } catch {}
          resolve(false);
        }
      });
    });

    conn.ws.on("error", (err) => {
      clearTimeout(timeout);
      warn(`[${conn.env}] WebSocket error: ${err.message}`);
      resolve(false);
    });

    conn.ws.on("close", () => {
      clearTimeout(timeout);
      if (conn.connected) {
        log(`[${conn.env}] Connection closed`);
        conn.connected = false;
        conn.authed = false;
        stopHeartbeat(conn);
        saveBasicState(conn);
        if (!conn.stopEvent) scheduleReconnectOne(conn);
      }
    });
  });
}

function disconnectOne(conn) {
  conn.stopEvent = true;
  conn.connected = false;
  conn.authed = false;
  stopHeartbeat(conn);
  if (conn.ws) {
    try { conn.ws.close(); } catch {}
    conn.ws = null;
  }
  saveBasicState(conn);
  log(`[${conn.env}] Disconnected`);
}

function scheduleReconnectOne(conn) {
  if (conn.stopEvent) return;
  conn.reconnectDelay = Math.min(conn.reconnectDelay * 1.5, CONFIG.reconnectMaxDelay);
  const delay = conn.reconnectDelay + Math.random() * 1000;
  setTimeout(() => {
    if (!conn.stopEvent) {
      connectOne(conn).then((ok) => {
        if (ok) conn.reconnectDelay = CONFIG.reconnectBaseDelay;
      });
    }
  }, delay);
}

// ── 消息读取（带 _source_env 标注） ──────────────────────────────

function setupReader(conn) {
  if (!conn.ws) return;
  conn.ws.removeAllListeners("message");
  conn.ws.on("message", (raw) => {
    try {
      const msg = JSON.parse(raw.toString());
      msg._source_env = conn.env; // R19: 标注来源环境
      handleMessage(msg, conn);
    } catch (err) {
      warn(`[${conn.env}] Bad JSON: ${raw.toString().slice(0, 100)}`);
    }
  });
}

function handleMessage(msg, conn) {
  const type = msg.type || "";

  if (type === "pong") return;

  if (type === "ack") {
    handleAck(msg);
    return;
  }

  if (type === "auth_ok") {
    conn.authed = true;
    log(`[${conn.env}] Re-auth OK`);
    return;
  }

  if (type === "auth_error") {
    warn(`[${conn.env}] Auth error: ${msg.error || ""}`);
    reportToUser(`❌ 认证错误（${conn.env}）: ${msg.error}`);
    return;
  }

  if (type === "pairing_code") {
    warn(`[${conn.env}] 重新配对: ${msg.code || "???"}`);
    reportToUser(`🔑 重新配对（${conn.env}）: ${msg.code}`);
    return;
  }

  if (type === "rate_limited") {
    const retryAfter = (msg.retry_after || 1) * 1000;
    warn(`[${conn.env}] Rate limited: ${msg.reason || ""}, waiting ${retryAfter}ms`);
    // 等待后自动重试最后一条待发送消息
    return;
  }

  if (type === "error") {
    warn(`[${conn.env}] Server error: ${msg.error || ""}`);
    return;
  }

  if (type === "delivery_status") {
    const msgId = msg.id || "";
    const total = msg.total || 0;
    const delivered = msg.delivered || 0;
    log(`[${conn.env}] Delivery status for ${msgId.slice(0, 12)}: ${delivered}/${total} delivered`);
    return;
  }

  if (type === "member_changed") {
    const wsId = msg.workspace_id || "?";
    const event = msg.event || "?";
    const name = msg.member_name || msg.target_agent_id || "?";
    log(`${event === "joined" ? "➕" : "➖"} ${name} ${event} workspace [${wsId}] (${conn.env})`);
    const b64 = Buffer.from(JSON.stringify({ type: "member_changed", workspace_id: wsId, event, member_name: name, env: conn.env }), "utf-8").toString("base64");
    console.log(`[MSG]system|system|${b64}`);
    return;
  }

  if (type === "workspace_assigned") {
    log(`[${conn.env}] 📋 Workspace assigned: ${msg.workspace_id || "?"}`);
    return;
  }

  if (type === "offline_messages") {
    const msgs = msg.messages || [];
    log(`[${conn.env}] Received ${msgs.length} offline messages`);
    for (const m of msgs) {
      m._source_env = conn.env;
      processBroadcast(m);
    }
    return;
  }

  if (type === "broadcast" || type === "message") {
    msg._source_env = conn.env;
    processBroadcast(msg);
    return;
  }

  log(`[${conn.env}] Unhandled: ${JSON.stringify(msg).slice(0, 100)}`);
}

function processBroadcast(msg) {
  const content = msg.content || "";
  const fromAgent = msg.from || msg.from_agent || "";
  const fromName = msg.from_name || (fromAgent ? fromAgent.slice(0, 20) : "unknown");
  const msgId = msg.id || "";
  const msgTs = msg.ts || 0;
  const sourceEnv = msg._source_env || "?";

  const mentions = msg.mentions || msg.is_task_assignment || null;

  if (fromAgent === CONFIG.agentId || fromName === CONFIG.botName) return;
  if (!content && !msgId) return;

  // 去重
  if (msgId) {
    if (seenIds.has(msgId)) return;
    seenIds.add(msgId);
    if (seenIds.size > SEEN_MAX) seenIds.clear();
  }

  // 更新 lastMsgTs（所有连接共享全局最大 ts）
  const conn = conns.get(sourceEnv);
  if (conn && msgTs > conn.lastMsgTs) {
    conn.lastMsgTs = msgTs;
    saveLastMsgTs(sourceEnv, msgTs);
  }

  log(`<< [${sourceEnv}][${fromName}] ${content.slice(0, 200)}`);

  // stdout 输出（带 _source_env）
  const envTag = sourceEnv !== "default" ? `[${sourceEnv}]` : "";
  const displayName = `${envTag}${fromName}`;
  const enrichedContent = content + (sourceEnv !== "default" ? `\n（来自 ${sourceEnv} 环境）` : "");
  const b64Content = Buffer.from(enrichedContent, "utf-8").toString("base64");
  let meta = "";
  if (mentions) {
    meta = `|${JSON.stringify(mentions)}`;
  }
  console.log(`[MSG]${displayName}|${fromAgent}|${b64Content}${meta}`);
}

// ── 发送消息（支持 _target_env） ─────────────────────────────────

function sendMessage(content, metaStr = "") {
  // 解析 _target_env 和 _channel：优先从 metaStr 取
  let targetEnv = DEFAULT_ENV;
  let channel = "lobby";
  let actualContent = content;

  if (metaStr) {
    // 解析多个 _xxx= 参数，用 | 分隔
    const parts = metaStr.split("|");
    for (const part of parts) {
      if (part.startsWith("_target_env=")) {
        targetEnv = part.slice("_target_env=".length);
      } else if (part.startsWith("_channel=")) {
        channel = part.slice("_channel=".length);
      }
    }
  } else if (content && content.startsWith("_target_env=")) {
    const pipeIdx = content.indexOf("|");
    if (pipeIdx > 0) {
      targetEnv = content.slice("_target_env=".length, pipeIdx);
      actualContent = content.slice(pipeIdx + 1);
    }
  }

  const conn = conns.get(targetEnv);
  if (!conn || !conn.ws || conn.ws.readyState !== WebSocket.OPEN || !conn.authed) {
    warn(`[${targetEnv}] Cannot send: not connected/authed`);
    return false;
  }

  const msgId = `${CONFIG.agentId.slice(0, 12)}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const hasChannel = metaStr.split("|").some(p => p.startsWith("_channel="));
  const isPrivate = metaStr && metaStr !== "*" && !hasChannel;
  // 支持 _channel 参数路由到指定 workspace，默认 lobby
  const msgChannel = isPrivate ? undefined : channel;
  const payload = isPrivate
    ? { type: "message", content: actualContent, to: metaStr, id: msgId, ts: Date.now() / 1000, _target_env: targetEnv }
    : { type: "message", channel: msgChannel, content: actualContent, id: msgId, ts: Date.now() / 1000, _target_env: targetEnv };

  doSendAndWaitAck(conn, msgId, payload, 0);
  return true;
}

function doSendAndWaitAck(conn, msgId, payload, attempt) {
  if (!conn.ws || conn.ws.readyState !== WebSocket.OPEN || !conn.authed) return;

  try {
    conn.ws.send(JSON.stringify(payload));
    const tag = attempt > 0 ? `RETRY ${payload.content.slice(0, 120)}` : payload.content.slice(0, 120);
    log(`[${conn.env}] >> ${tag} (id=${msgId.slice(0, 8)})`);
  } catch (err) {
    warn(`[${conn.env}] Send error: ${err.message}`);
    return;
  }

  if (pendingAcks.has(msgId)) {
    const entry = pendingAcks.get(msgId);
    clearTimeout(entry.timeoutTimer);
    entry.timeoutTimer = setTimeout(() => ackTimeoutHandler(msgId), CONFIG.ackTimeout);
    return;
  }

  const timeoutTimer = setTimeout(() => ackTimeoutHandler(msgId), CONFIG.ackTimeout);
  pendingAcks.set(msgId, {
    resolve: () => {},
    reject: () => {},
    timeoutTimer,
    retryCount: attempt,
    payload,
    conn,
  });
}

function ackTimeoutHandler(msgId) {
  const entry = pendingAcks.get(msgId);
  if (!entry) return;

  if (entry.retryCount < CONFIG.maxRetries) {
    entry.retryCount++;
    warn(`[${entry.conn.env}] No ACK for msg ${msgId.slice(0, 8)} (retry ${entry.retryCount}/${CONFIG.maxRetries})`);
    entry.payload.ts = Date.now() / 1000;
    doSendAndWaitAck(entry.conn, msgId, entry.payload, entry.retryCount);
  } else {
    warn(`[${entry.conn.env}] Message ${msgId.slice(0, 8)} failed after ${CONFIG.maxRetries + 1} attempts`);
    pendingAcks.delete(msgId);
    reportToUser(`⚠️ 消息发送失败（${entry.conn.env}，重试 ${CONFIG.maxRetries + 1} 次后）：${entry.payload.content.slice(0, 80)}`);
  }
}

function handleAck(msg) {
  const ackId = msg.id || "";
  if (!ackId) return;
  const entry = pendingAcks.get(ackId);
  if (entry) {
    clearTimeout(entry.timeoutTimer);
    pendingAcks.delete(ackId);
    log(`[${entry.conn.env}] ACK received for ${ackId.slice(0, 8)}`);
  }
}

function pendingAcksClear() {
  for (const entry of pendingAcks.values()) {
    clearTimeout(entry.timeoutTimer);
  }
  pendingAcks.clear();
}

// ── 文件管道（SEND 协议升级） ──────────────────────────────────

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
      for (const line of newContent.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        if (trimmed === "PING") {
          console.log("[STATUS]alive");
        } else if (trimmed === "STATUS") {
          const statuses = [];
          for (const [env, c] of conns) {
            statuses.push(`${env}:connected=${c.connected}|authed=${c.authed}`);
          }
          console.log(`[STATUS]${statuses.join(" ")}`);
        } else if (trimmed.startsWith("SEND|")) {
          const rest = trimmed.slice(5);
          // 支持 SEND|_meta1=val1|_meta2=val2|...|content
          // meta 都以 _ 开头（_xxx=value），多个 meta 用 | 分隔
          // 例: SEND|_target_env=production|_channel=ws:R20开发工作室|你好
          // 解析：前序所有 _xxx= 段为 meta，后续段为内容
          const parts = rest.split("|");
          const metaList = [];
          let contentParts = [];
          let parsingMeta = true;
          for (const part of parts) {
            if (parsingMeta && /^_[a-z_]+=/.test(part)) {
              metaList.push(part);
            } else {
              parsingMeta = false;
              contentParts.push(part);
            }
          }
          if (metaList.length > 0) {
            const metaStr = metaList.join("|");
            const msgContent = contentParts.join("|");
            sendMessage(msgContent, metaStr);
          } else {
            sendMessage(rest);
          }
        }
      }
      pipeLastSize = stats.size;
    } catch {}
  });
}

let pipeWatcher = null;
let pipeLastSize = 0;

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
    for (const line of chunk.toString().split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (trimmed === "PING") {
        console.log("[STATUS]alive");
      } else if (trimmed === "STATUS") {
        const statuses = [];
        for (const [env, c] of conns) {
          statuses.push(`${env}:connected=${c.connected}|authed=${c.authed}`);
        }
        console.log(`[STATUS]${statuses.join(" ")}`);
      } else if (trimmed.startsWith("SEND|")) {
        const rest = trimmed.slice(5);
        if (rest.startsWith("_target_env=")) {
          const pipeIdx = rest.indexOf("|");
          if (pipeIdx > 0) {
            const metaStr = rest.slice(0, pipeIdx);
            const msgContent = rest.slice(pipeIdx + 1);
            sendMessage(msgContent, metaStr);
          }
        } else {
          sendMessage(rest);
        }
      }
    }
  });
}

// ── 启动 ──────────────────────────────────────────────────────────

async function main() {
  log(`${CONFIG.botName} starting...`);
  log(`  Environments: ${urlConns.map((c) => `${c.env}:${c.url}`).join(", ")}`);
  log(`  Agent:  ${CONFIG.agentId}`);

  // 创建所有连接
  for (const { env, url } of urlConns) {
    const conn = createConnState(env, url);
    conns.set(env, conn);
  }

  setupStdin();
  startPipeWatcher();

  // 保存初始状态
  for (const conn of conns.values()) {
    saveBasicState(conn);
  }

  // 连接所有环境
  const results = await Promise.all(
    Array.from(conns.values()).map((conn) => connectOne(conn))
  );

  const allOk = results.every(Boolean);
  if (allOk) {
    log("All environments connected");
    if (urlConns.length > 1) {
      reportToUser(`✅ 多环境 ws-bridge 已接入: ${urlConns.map((c) => c.env).join(", ")}`);
    }
  } else {
    log("Some environments failed initial connect — will retry");
  }

  process.stdin.resume();
}

process.on("SIGINT", () => {
  log("SIGINT received");
  for (const conn of conns.values()) disconnectOne(conn);
  process.exit(0);
});

process.on("SIGTERM", () => {
  log("SIGTERM received");
  for (const conn of conns.values()) disconnectOne(conn);
  process.exit(0);
});

process.on("uncaughtException", (err) => {
  warn(`Uncaught: ${err.message}`);
});

main().catch((err) => {
  warn(`Fatal: ${err.message}`);
  process.exit(1);
});
