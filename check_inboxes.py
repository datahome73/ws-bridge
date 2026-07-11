import asyncio, json, websockets, os, time

async def check_inboxes():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'🔑 认证通过 agent_id={creds["agent_id"]}')
        print(f'📬 小谷 inbox: {resp.get("active_channel", "N/A")}')
        print()

        # 逐个查所有人的卡片详情
        bots = ['小谷', '小爱', '小开', '爱泰', '小周', '泰虾']
        for name in bots:
            await asyncio.sleep(1.5)  # rate limit
            payload = {
                'type': 'message',
                'content': f'!agent_card get {name}',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': f'get-{name}-' + str(int(time.time())),
                'ts': time.time(),
            }
            await ws.send(json.dumps(payload))
            print(f'📤 查 {name}...')
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(msg)
                content = data.get('content', '')
                if content:
                    print(f'📩 {content}')
                else:
                    print(f'📩 {str(data)[:300]}')
            except asyncio.TimeoutError:
                print(f'⏱️ {name}: 超时')
            print()

asyncio.run(check_inboxes())
