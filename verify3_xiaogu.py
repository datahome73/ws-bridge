import asyncio, json, websockets, os

async def verify():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        # 认证
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f'🔑 {json.dumps(resp, ensure_ascii=False)}')
        assert resp.get('type') == 'auth_ok'

        # 用 message 格式发 !agent_card list
        payload = {
            'type': 'message',
            'content': '!agent_card list',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': 'verify-' + creds['agent_id'][:8],
            'ts': __import__('time').time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 已发送 !agent_card list，等待响应...')

        # 等几秒收消息
        for i in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                print(f'📩 [{i}] {msg[:500]}')
            except asyncio.TimeoutError:
                print(f'⏱️ [{i}] 超时')

asyncio.run(verify())
