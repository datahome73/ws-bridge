import asyncio, json, websockets, os, time, uuid

async def test_ack():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ 认证通过')

        # 1. 先发一条 lobby 消息（无 to），看 ACK 是否正常
        msg_id = str(uuid.uuid4())
        payload = {
            'type': 'message',
            'content': 'inbox测试 - 小谷发的',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id,
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f'📤 Lobby (id={msg_id[:8]})', end='')
        for _ in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'ack' and data.get('id') == msg_id:
                    print(f' ✅ ACK')
                    break
                elif mt == 'broadcast':
                    print(f' ✅ 广播回显: {data.get("content","")[:80]}')
                    break
                else:
                    print(f' 📩 type={mt}')
            except asyncio.TimeoutError:
                print(f' ⏱️ 超时')
                break

        # 2. 等两秒再发 DM
        await asyncio.sleep(2)
        msg_id2 = str(uuid.uuid4())
        payload2 = {
            'type': 'message',
            'content': 'inbox测试 - 小谷发的',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id2,
            'ts': time.time(),
            'to': '@小爱',
        }
        await ws.send(json.dumps(payload2))
        print(f'📤 DM->小爱 (id={msg_id2[:8]})', end='')
        for _ in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'ack' and data.get('id') == msg_id2:
                    print(f' ✅ ACK')
                    break
                print(f' 📩 type={mt} content={str(data)[:150]}')
            except asyncio.TimeoutError:
                print(f' ⏱️ 超时')
                break

asyncio.run(test_ack())
