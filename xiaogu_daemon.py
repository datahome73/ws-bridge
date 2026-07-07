import asyncio, json, websockets, os, time

MY_INBOX_RATE_LIMIT = {}  # sender_id -> last_reply_ts

async def run():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    AGENT_ID = creds['agent_id']
    API_KEY = creds['api_key']
    MY_INBOX = f"_inbox:{AGENT_ID}"
    WS_URL = 'wss://wsim.datahome73.cloud/ws'

    while True:
        try:
            async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": API_KEY}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                assert resp.get("type") == "auth_ok"
                print(f"🟢 小谷已上线 agent_id={AGENT_ID}")

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    ch = data.get("channel", "")
                    msg_type = data.get("type", "")

                    # ── 仅处理投递到小谷收件箱的消息 ──
                    if ch != MY_INBOX or msg_type not in ("broadcast", "message"):
                        continue

                    sender_id = data.get("agent_id", "")
                    sender_name = data.get("from_name", sender_id[:12])

                    # 不回复自己（理论上 server 已阻止自写，双重保护）
                    if sender_id == AGENT_ID:
                        continue

                    if not sender_id:
                        continue

                    # 速率限制：同一发件人每 15 秒最多回一条
                    now = time.time()
                    last = MY_INBOX_RATE_LIMIT.get(sender_id, 0)
                    if now - last < 15:
                        continue
                    MY_INBOX_RATE_LIMIT[sender_id] = now

                    content = data.get("content", "")
                    print(f"\n📩 小谷收件箱 [{sender_name}]: {content[:200]}")

                    # 回复到发件人收件箱
                    sender_inbox = f"_inbox:{sender_id}"
                    reply_content = f"✅ 小谷已收到你的消息。"
                    await ws.send(json.dumps({
                        "type": "message",
                        "channel": sender_inbox,
                        "content": reply_content,
                        "from_name": "小谷",
                        "agent_id": AGENT_ID,
                        "id": f"auto-reply-{int(now)}-{sender_id[:8]}",
                        "ts": now,
                    }))
                    print(f"📤 已自动回复到 {sender_name} 收件箱")

                    # ── 转发出站消息到大厅，激活 PM（Hermes）──
                    # 让 PM 看到 bot 的回复内容，可以判断是否需要推进管线
                    forward_msg = f"📩 [{sender_name}] 回复小谷: {content[:500]}"
                    await ws.send(json.dumps({
                        "type": "message",
                        "channel": "lobby",
                        "content": forward_msg,
                        "from_name": "小谷",
                        "agent_id": AGENT_ID,
                        "id": f"fwd-{int(now)}-{sender_id[:8]}",
                        "ts": now,
                    }))


                    # ── 写入本地通知文件，供 PM 检查 ──
                    # 每次收到 bot 回复，追加到 pipeline_notify.jsonl
                    notify_dir = os.path.expanduser("~/.ws-bridge")
                    os.makedirs(notify_dir, exist_ok=True)
                    notify_path = os.path.join(notify_dir, "pipeline_notify.jsonl")
                    try:
                        with open(notify_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({
                                "ts": now,
                                "sender_id": sender_id,
                                "sender_name": sender_name,
                                "content": content[:500],
                            }, ensure_ascii=False) + "\n")
                    except OSError:
                        pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"🔴 断线 ({e})，3秒后重连")
            await asyncio.sleep(3)

try:
    asyncio.run(run())
except KeyboardInterrupt:
    print("👋 小谷下线")
