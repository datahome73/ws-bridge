import asyncio, json, websockets, os, time

async def check():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'

        payload = {
            'type': 'message',
            'content': '!agent_card list',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': 'check-all-' + creds['agent_id'][:6],
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))

        for i in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'content' in data:
                    print(data['content'])
                else:
                    print(f'[{i}] type={data.get("type")}: {str(data)[:300]}')
            except asyncio.TimeoutError:
                break

asyncio.run(check())
