#!/usr/bin/env python3
"""Final inbox test — 用真实 agent_ids 逐个测试"""
import asyncio, json, websockets, os, time

REAL_IDS = {
    "小开": "ws_3f7cdd736c1c",
    "爱泰": "ws_0bb747d3ea2a",
    "小周": "ws_fcf496ca1b4f",
    "泰虾": "ws_eab784ac7652",
    "小爱": "ws_c47032fa1f67",
}

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过\n")

        print("=" * 60)
        print("📬 Inbox 逐个收发测试（真实 agent_id）")
        print("=" * 60)

        order = ["小开", "爱泰", "小周", "泰虾", "小爱"]
        results = {}

        for name in order:
            aid = REAL_IDS[name]
            inbox_ch = f"_inbox:{aid}"
            
            print(f"\n{'─' * 50}")
            print(f"📤 [{name}] → {inbox_ch}")
            
            await asyncio.sleep(2.5)
            await ws.send(json.dumps({
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 inbox收发测试 - 小谷→{name}，通过收件箱发送，收到请回复 @小谷',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            
            got_ack = False
            sent_count = 0
            got_reply = False
            reply_text = ""
            
            for i in range(25):  # ~37s max
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    
                    if mt == 'ack':
                        sent = data.get('sent', 0)
                        sent_count = sent
                        got_ack = True
                        status = "🎯 投递成功" if sent > 0 else "⚠️ 无在线连接"
                        print(f"   ✅ ACK (sent={sent}) {status}")
                    elif mt == 'broadcast':
                        fn = data.get('from_name', '?')
                        ct = data.get('content', '')
                        ch = data.get('channel', '')
                        if ch.startswith('_inbox:') and fn == '小谷':
                            pass  # inbox echo
                        elif fn == name:
                            got_reply = True
                            reply_text = ct
                            print(f"   📩 [{fn}] 回复: {ct[:150]}")
                        elif fn in REAL_IDS or '收到' in ct:
                            print(f"   📩 [{fn}]: {ct[:120]}")
                    elif mt == 'error':
                        print(f"   ❌ 错误: {data.get('error', '')}")
                except asyncio.TimeoutError:
                    pass
            
            deliver_status = "✅ 已投递" if sent_count > 0 else "⚠️ 未在线"
            reply_status = "+ 已回复" if got_reply else ""
            print(f"📊 {name}: {deliver_status} {reply_status}")
            
            results[name] = {
                "sent": sent_count,
                "replied": got_reply,
                "reply": reply_text[:80] if reply_text else "",
            }

        # 汇总
        print(f"\n{'=' * 60}")
        print("📊 测试汇总")
        print(f"{'=' * 60}")
        all_delivered = True
        for name, r in results.items():
            icon = "✅" if r["sent"] > 0 else "⚠️"
            reply = "📩 已回复" if r["replied"] else ""
            print(f"  {icon} {name:6s}: inbox 投递{'成功' if r['sent']>0 else '失败(离线)'} {reply}")
            if r["sent"] == 0:
                all_delivered = False

        if all_delivered:
            print(f"\n🎉 全部投递成功！inbox 系统正常")
        else:
            print(f"\n⚠️ 部分 bot 不在线（sent=0）")

        # 更新 credential 文件的 agent_id
        print(f"\n📝 更新 credential 文件 agent_id...")
        for name, real_id in REAL_IDS.items():
            fpath = os.path.expanduser(f'~/.ws-bridge/{name}.json')
            cred = json.load(open(fpath))
            old_id = cred.get('agent_id', '?')
            if old_id != real_id:
                cred['agent_id'] = real_id
                json.dump(cred, open(fpath, 'w'), ensure_ascii=False, indent=2)
                print(f"   ✅ {name}: {old_id} → {real_id}")
            else:
                print(f"   ✓ {name}: 已正确")
        print(f"\n✅ 测试完成")

asyncio.run(test())
