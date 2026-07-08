#!/usr/bin/env python3
"""
Inbox 收发测试 — 逐个点名小开→其他 bot
流程：连小谷→发 inbox 到小开→等人回→继续下一位
"""
import asyncio, json, websockets, os, time

BOTS_IN_ORDER = ["小开", "爱泰", "小周", "泰虾", "小爱"]

# 从 credential 文件读 agent_id（用户已确认小爱 +15min 收到并回复了 inbox）
BOT_AGENTS = {}
for name in BOTS_IN_ORDER:
    try:
        c = json.load(open(os.path.expanduser(f'~/.ws-bridge/{name}.json')))
        BOT_AGENTS[name] = c['agent_id']
    except: pass
BOT_AGENTS["小谷"] = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))['agent_id']

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    print("=" * 60)
    print("📬 Inbox 逐个收发测试")
    print("   发送方: 小谷 (PM)")
    print("   从 " + BOTS_IN_ORDER[0] + " 开始")
    print("=" * 60)

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 认证通过\n")

        results = {}

        for name in BOTS_IN_ORDER:
            aid = BOT_AGENTS.get(name, "?")
            inbox_ch = f"_inbox:{aid}"
            
            print(f"\n{'─' * 50}")
            print(f"📤 [{name}] → {inbox_ch}")
            
            # 发 inbox 消息
            await asyncio.sleep(2.5)  # rate limit
            await ws.send(json.dumps({
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 inbox收发测试 - 小谷→{name}，这条消息通过 inbox 通道发送，收到请用 @小谷 回复',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            
            got_ack = False
            got_reply = False
            reply_from = ""
            reply_content = ""
            
            # 等 ACK + 等 bot 回复（最长 30s）
            for i in range(20):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    
                    if mt == 'ack':
                        sent = data.get('sent', 0)
                        ch = data.get('channel', '')
                        print(f"   ✅ ACK (sent={sent})")
                        got_ack = True
                    elif mt == 'broadcast':
                        fn = data.get('from_name', '?')
                        ct = data.get('content', '')
                        ch = data.get('channel', '')
                        reply_from = fn
                        reply_content = ct
                        
                        if name in str(fn):
                            got_reply = True
                            print(f"   📩 [{fn}] 回复: {ct[:120]}")
                        elif ch.startswith('_inbox:'):
                            # inbox 回音
                            print(f"   📩 [inbox回声] {fn}: {ct[:80]}")
                        else:
                            # 其他广播
                            if '小谷' in ct or '回复' in ct or '收到' in ct:
                                print(f"   📩 [{fn}]: {ct[:120]}")
                                if '收到' in ct or '回复' in ct:
                                    got_reply = True
                            else:
                                print(f"   📩 [{fn}]: {ct[:80]}")
                    elif mt == 'error':
                        print(f"   ❌ 错误: {data.get('error','')}")
                    else:
                        print(f"   [{i}] type={mt}: {str(data)[:100]}")
                        
                except asyncio.TimeoutError:
                    pass
            
            status = "✅ 通" if got_ack else "❌ 不通"
            if got_reply:
                status += f" + 收到回复"
            elif got_ack:
                status += " (ACK 正常，等回复中...)"
                
            results[name] = {
                "ack": got_ack,
                "reply": got_reply,
                "reply_from": reply_from,
                "reply_content": reply_content[:100] if reply_content else "",
            }
            print(f"📊 {name}: {status}")

        # 汇总
        print(f"\n{'=' * 60}")
        print("📊 测试汇总")
        print(f"{'=' * 60}")
        all_ok = True
        for name, r in results.items():
            icon = "✅" if r["ack"] else "❌"
            reply_icon = "📩" if r["reply"] else ""
            print(f"  {icon} {name:6s}: inbox {'可发送' if r['ack'] else '不通'} {reply_icon}")
            if not r["ack"]:
                all_ok = False
        
        if all_ok:
            print(f"\n🎉 所有 bot inbox 收发正常！")
        else:
            print(f"\n⚠️ 有异常需要排查")

asyncio.run(test())
