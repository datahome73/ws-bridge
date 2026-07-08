import asyncio, json, websockets, os, time, uuid

async def test_dm():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ 认证通过 agent_id={creds["agent_id"]}')

        # 给每个 bot 发一条 DM 测试 inbox 路由
        bots = ['小爱', '小开', '爱泰', '小周', '泰虾']
        for name in bots:
            await asyncio.sleep(1.5)
            msg_id = str(uuid.uuid4())
            payload = {
                'type': 'message',
                'content': f'@小谷 inbox测试 - 这条消息发给你({name})，收到请回',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': msg_id,
                'ts': time.time(),
                'to': f'@{name}',
            }
            await ws.send(json.dumps(payload))
            print(f'📤 DM -> {name} (id={msg_id[:8]})')

            # 看有没有回音
            for _ in range(3):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    content = str(data)[:250]
                    if 'ack' in str(data.get('type', '')):
                        print(f'   ✅ ACK from {name}')
                    elif 'content' in data and name in data.get('from_name', ''):
                        print(f'   📩 {data.get("from_name")}: {data.get("content", "")[:100]}')
                    else:
                        print(f'   📩 {content}')
                except asyncio.TimeoutError:
                    break

asyncio.run(test_dm())
