import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        await asyncio.sleep(15)

        # 不带目标的点名
        payload = {
            'type': 'message',
            'content': '📋点名',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 "📋点名"')

        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    print(f'📩 [{i}s] 广播 [{data.get("from_name","?")}]: {data.get("content","")[:300]}')
                elif mt == 'ack':
                    print(f'✅ [{i}s] ACK')
                elif mt == 'error':
                    print(f'❌ [{i}s] {data.get("error","")}')
                else:
                    print(f'📩 [{i}s] type={mt}: {str(data)[:300]}')
            except asyncio.TimeoutError:
                pass

        # 📢公告
        await asyncio.sleep(5)
        payload2 = {
            'type': 'message',
            'content': '📢公告 各位，我是小谷，通过 R72 新认证连接的。测试广播是否正常。',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload2))
        print('\n📤 "📢公告"')
        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    print(f'📩 [{i}s] 广播 [{data.get("from_name","?")}]: {data.get("content","")[:300]}')
                elif mt == 'ack':
                    print(f'✅ [{i}s] ACK')
                elif mt == 'error':
                    print(f'❌ [{i}s] {data.get("error","")}')
                else:
                    print(f'📩 [{i}s] type={mt}: {str(data)[:300]}')
            except asyncio.TimeoutError:
                pass

asyncio.run(test())
