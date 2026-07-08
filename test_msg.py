import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth_ok, active_channel={resp.get("active_channel")}')

        # 发 lobby 消息
        msg_id = str(uuid.uuid4())
        payload = {
            'type': 'message',
            'content': 'test',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id,
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f'📤 sent (id={msg_id[:8]})')

        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                print(f'📩 [{i}] {json.dumps(data, ensure_ascii=False)[:500]}')
            except asyncio.TimeoutError:
                print(f'⏱️ [{i}] 超时')
                break

asyncio.run(test())
