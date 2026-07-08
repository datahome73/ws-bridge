import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        # 1. 发 !pipeline_status 看命令是否可用
        payload = {
            'type': 'message',
            'content': '!pipeline_status',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 !pipeline_status')
        await asyncio.sleep(3)
        for i in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                print(f'  [{i}] {str(data)[:300]}')
            except asyncio.TimeoutError:
                break

        await asyncio.sleep(2)

        # 2. 再发一次 @小爱
        msg_id = str(uuid.uuid4())
        payload2 = {
            'type': 'message',
            'content': '@小爱 gateway测试 - 我是小谷',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id,
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload2))
        print(f'\n📤 @小爱 (id={msg_id[:8]})')
        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                print(f'  [{i}] {str(data)[:300]}')
            except asyncio.TimeoutError:
                break

asyncio.run(test())
