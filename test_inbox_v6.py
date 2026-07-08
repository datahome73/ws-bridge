#!/usr/bin/env python3
"""查 card 里的完整 agent_id"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        
        # 用 !agent_card list 拿完整列表
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message', 'content': '!agent_card list',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'list-{int(time.time())}', 'ts': time.time(),
        }))
        await asyncio.sleep(2)
        
        cards_text = ""
        for _ in range(8):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if 'content' in data:
                    cards_text += data['content'] + "\n"
            except asyncio.TimeoutError:
                break
        
        print("📋 当前 Agent Cards:")
        print(cards_text)
        
        # !agent_card list 没有显示 agent_id
        # 换个方式：查 Chat 日志能看到消息的 agent_id
        # 直接让小爱回复一条，抓她的 agent_id
        print("\n💡 尝试大厅点名...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小爱 请回复你的 agent_id，方便 inbox 测试',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'ask-{int(time.time())}', 'ts': time.time(),
        }))
        
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if data.get('type') == 'broadcast':
                    fn = data.get('from_name', '?')
                    aid = data.get('agent_id', '?')
                    ct = data.get('content', '')
                    print(f"  📩 [{fn}] agent_id={aid}: {ct[:150]}")
                    
                    # 如果小爱回复了，用她的 agent_id 发 inbox
                    if '小爱' in str(fn) or ('收到' in ct and '小爱' in fn):
                        print(f"\n🎯 小爱 agent_id = {aid}")
                        # 发 inbox 到小爱
                        inbox_ch = f"_inbox:{aid}"
                        await asyncio.sleep(2)
                        await ws.send(json.dumps({
                            'type': 'message', 'channel': inbox_ch,
                            'content': f'📋 inbox测试 - 小谷→小爱（agent_id={aid[:12]}），通过收件箱发的',
                            'from_name': '小谷', 'agent_id': my_id,
                            'id': f'inbox-xiaoai-{int(time.time())}', 'ts': time.time(),
                        }))
                        for _ in range(5):
                            try:
                                msg2 = await asyncio.wait_for(ws.recv(), timeout=2)
                                data2 = json.loads(msg2)
                                if data2.get('type') == 'ack':
                                    print(f"   ✅ Inbox to 小爱: sent={data2.get('sent',0)}")
                                    break
                                elif data2.get('type') == 'broadcast' and data2.get('channel','').startswith('_inbox:'):
                                    print(f"   📩 小爱 inbox 的回声收到!")
                                    break
                            except asyncio.TimeoutError:
                                break
            except asyncio.TimeoutError:
                pass

asyncio.run(test())
