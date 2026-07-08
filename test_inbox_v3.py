#!/usr/bin/env python3
"""Inbox 测试 v3 — 逐个查 agent_id 并收件箱发送"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过 | agent_id={creds['agent_id']}")
        print(f"   活跃频道: {resp.get('active_channel', 'N/A')}\n")

        # 查 !agent_card list 拿到各 bot 的实际 agent_id
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message', 'content': '!agent_card list',
            'from_name': '小谷', 'agent_id': creds['agent_id'],
            'id': f'list-{int(time.time())}', 'ts': time.time(),
        }))
        await asyncio.sleep(3)
        
        cards_raw = ""
        for _ in range(8):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if 'content' in data:
                    cards_raw += data['content'] + "\n"
                    print(f"  {data['content']}")
            except asyncio.TimeoutError:
                break
        print()

        # 提取每个 card 的 agent_id
        # 格式: 小开 [architect] status=online agent_id=ws_xxx
        card_agents = {}
        for line in cards_raw.split("\n"):
            line = line.strip()
            # Match: 小开 [architect] status=online agent_id=ws_xxx
            if 'agent_id=' in line:
                parts = line.split()
                # first part is the name
                name = parts[0] if parts else ""
                for p in parts:
                    if p.startswith('agent_id='):
                        aid = p.split('=', 1)[1]
                        card_agents[name] = aid
        
        if not card_agents:
            # 备选：用已知 agent_ids
            card_agents = {
                "小开": "ws_f8a816527f9e",
                "爱泰": "ws_0ee70be2d59e",
                "小周": "ws_4e1a1b3ba0b9",
                "泰虾": "ws_cd771242975a",
                "小爱": "ws_7f0e931af04b",
                "小谷": "ws_f26e585f6479",
            }
            print("⚠️ 未从卡片提取到 agent_id，使用已知 IDs")
        
        print(f"📋 Agent IDs:")
        for name, aid in card_agents.items():
            print(f"   {name}: {aid}")
        print()

        # 逐个发 inbox 消息
        print("=" * 60)
        print("📤 逐个发送 inbox 消息")
        print("=" * 60)
        
        test_results = {}
        for name, agent_id in card_agents.items():
            if name == "小谷":
                continue  # 不发自己
            
            inbox_ch = f"_inbox:{agent_id}"
            await asyncio.sleep(2)
            
            await ws.send(json.dumps({
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 inbox测试 - 小谷→{name}，收到请回复 @小谷',
                'from_name': '小谷', 'agent_id': creds['agent_id'],
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            
            got_ack = False
            got_error = False
            sent_count = 0
            for _ in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    if data.get('type') == 'ack':
                        sent_count = data.get('sent', 0)
                        got_ack = True
                        break
                    elif data.get('type') == 'error':
                        got_error = True
                        test_results[name] = f"❌ {data.get('error','unknown error')}"
                        break
                except asyncio.TimeoutError:
                    break
            
            if got_error:
                print(f"  ❌ {name:6s} → {inbox_ch}: {test_results[name]}")
            elif got_ack:
                status = "✅ ACK (sent=" + str(sent_count) + ")"
                test_results[name] = f"✅ ACK (sent={sent_count})"
                print(f"  ✅ {name:6s} → {inbox_ch}: {status}")
            else:
                test_results[name] = "⚠️ 无响应"
                print(f"  ⚠️ {name:6s} → {inbox_ch}: 无响应")
        
        # 汇总
        print("\n" + "=" * 60)
        print("📊 测试结果")
        print("=" * 60)
        for name, result in test_results.items():
            print(f"  {name:6s}: {result}")
        
        # 再发一条 @all 到大厅看谁能回复
        print(f"\n📤 大厅广播点名...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小开 @爱泰 @小周 @泰虾 @小爱 inbox测试确认 - 收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': creds['agent_id'],
            'id': f'lobby-{int(time.time())}', 'ts': time.time(),
        }))
        print("   等待 15 秒收回复...")
        for _ in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                if data.get('type') == 'broadcast':
                    fn = data.get('from_name', '?')
                    ct = data.get('content', '')
                    print(f"  📩 [{fn}]: {ct[:150]}")
            except asyncio.TimeoutError:
                pass
        
        print("\n✅ 测试完成")

asyncio.run(test())
