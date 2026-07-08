import asyncio, json, websockets, os, time

async def check_inboxes():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        # auth
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        my_agent_id = creds['agent_id']
        inbox = resp.get('active_channel', 'N/A')
        print(f'✅ 认证通过 agent_id={my_agent_id}')
        print(f'📬 小谷 active_channel = {inbox}')
        print()

        # !agent_card list 再拿一次完整的卡信息
        payload = {
            'type': 'message', 'content': '!agent_card list',
            'from_name': '小谷', 'agent_id': my_agent_id,
            'id': 'list-' + str(int(time.time())), 'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        await asyncio.sleep(3)
        for _ in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'content' in data:
                    print(f'📋 {data["content"]}')
            except asyncio.TimeoutError:
                break
        print()

        # 查自己的卡
        await asyncio.sleep(2)
        payload = {
            'type': 'message', 'content': f'!agent_card get {my_agent_id}',
            'from_name': '小谷', 'agent_id': my_agent_id,
            'id': 'get-self-' + str(int(time.time())), 'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        await asyncio.sleep(2)
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'content' in data:
                    print(f'📇 小谷详情: {data["content"]}')
                else:
                    print(f'📇 {str(data)[:300]}')
            except asyncio.TimeoutError:
                break

asyncio.run(check_inboxes())
