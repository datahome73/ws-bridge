#!/usr/bin/env python3
"""测试 inbox 消息收发 — 逐个 bot 走一遍"""
import asyncio, json, websockets, os, time, uuid

BOTS = {
    "小开": "ws_f8a816527f9e",
    "爱泰": "ws_0ee70be2d59e",
    "小周": "ws_4e1a1b3ba0b9",
    "泰虾": "ws_cd771242975a",
    "小爱": "ws_7f0e931af04b",
}

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    uri = 'wss://wsim.datahome73.cloud/ws'

    print("=" * 60)
    print(f"🧪 Inbox 收发测试 — 发送方: 小谷 (PM)")
    print(f"    agent_id: {creds['agent_id']}")
    print("=" * 60)

    async with websockets.connect(uri, max_size=2**20) as ws:
        # 认证
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"\n✅ 认证通过\n")

        # 按小开→爱泰→小周→泰虾→小爱 逐个发 inbox 消息
        results = {}
        for name, agent_id in BOTS.items():
            inbox_ch = f"_inbox:{agent_id}"
            await asyncio.sleep(2)  # rate limit

            payload = {
                'type': 'message',
                'channel': inbox_ch,
                'content': f'@小谷 inbox测试 - 发给{name}的收件箱，收到请用 @小谷 回复',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': f'inbox-test-{name}-{int(time.time())}',
                'ts': time.time(),
            }
            await ws.send(json.dumps(payload))
            print(f"📤 [{name}] → {inbox_ch}")

            # 等响应
            got_ack = False
            got_error = False
            got_reply = False
            reply_content = ""
            for i in range(10):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    if mt == 'ack':
                        sent = data.get('sent', 0)
                        ch = data.get('channel', '')
                        print(f"   ✅ ACK: sent={sent}, to={data.get('to','')[:16]}")
                        got_ack = True
                    elif mt == 'error':
                        err = data.get('error', '')
                        print(f"   ❌ 错误: {err}")
                        got_error = True
                        reply_content = err
                    elif mt == 'broadcast':
                        fn = data.get('from_name', '?')
                        ct = data.get('content', '')
                        print(f"   📩 [{fn}]: {ct[:120]}")
                        got_reply = True
                        reply_content = ct
                    else:
                        print(f"   📩 [{i}] type={mt}: {str(data)[:200]}")
                except asyncio.TimeoutError:
                    break

            results[name] = {
                "ack": got_ack,
                "error": got_error,
                "reply": got_reply,
                "reply_content": reply_content[:100] if reply_content else "",
                "target_agent": agent_id,
            }
            print()

        # 汇总
        print("=" * 60)
        print("📊 测试结果汇总")
        print("=" * 60)
        all_ok = True
        for name, r in results.items():
            if r["ack"] and not r["error"]:
                status = "✅ 通"
            elif r["error"]:
                status = f"❌ 不通 ({r['reply_content'][:60]})"
                all_ok = False
            else:
                status = "⚠️ 无响应"
                all_ok = False
            print(f"  {name:6s} ({r['target_agent'][:16]:16s}) → {status}")

        print()
        if all_ok:
            print("🎉 全部 OK！inbox 收发正常")
        else:
            print("⚠️ 有异常，需进一步排查")

asyncio.run(test())
