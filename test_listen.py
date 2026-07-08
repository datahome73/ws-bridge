import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f'✅ auth: channel={resp.get("active_channel")}')
        my_id = creds['agent_id']

        # 不发送，直接监听 10 秒，看有没有任何消息流入
        print('📡 监听 10 秒...')
        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                print(f'📩 [{i}s] type={data.get("type")}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                pass

        # 发一条点名到 lobby
        await asyncio.sleep(2)
        payload = {
            'type': 'message',
            'content': '📋点名 小爱 inbox测试',
            'from_name': '小谷',
            'agent_id': my_id,
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('\n📤 发了点名，再监听 8 秒...')

        for i in range(8):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                print(f'📩 [{i}s] type={data.get("type")}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                pass

asyncio.run(test())
