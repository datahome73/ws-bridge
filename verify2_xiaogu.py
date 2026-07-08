import asyncio, json, websockets, os

async def verify():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        # 认证
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f'🔑 {json.dumps(resp, ensure_ascii=False)}')
        assert resp.get('type') == 'auth_ok'

        # 查自己卡片
        await ws.send(json.dumps({'type': 'get_agent_card', 'agent_id': creds['agent_id']}))
        try:
            card = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print(f'📇 card: {json.dumps(card, ensure_ascii=False)}')
        except asyncio.TimeoutError:
            print('⚠️ get_agent_card 超时，改用 agent_card_get')
            await ws.send(json.dumps({'type': 'agent_card_get', 'agent_id': creds['agent_id']}))
            card = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print(f'📇 card: {json.dumps(card, ensure_ascii=False)}')

        # 尝试用文本命令 !agent_card list
        await ws.send('!agent_card list')
        try:
            result = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f'📋 {result}')
        except asyncio.TimeoutError:
            print('⚠️ !agent_card list 超时')

asyncio.run(verify())
