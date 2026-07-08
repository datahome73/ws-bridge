import asyncio, json, websockets, os

async def verify():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok', f'认证失败: {resp}'
        print(f'✅ 认证通过')

        # 查自己的在线状态
        await ws.send(json.dumps({'type': 'agent_card_get', 'agent_id': creds['agent_id']}))
        card = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f'📡 status={card.get("status")}, display_name={card.get("display_name")}')

asyncio.run(verify())
