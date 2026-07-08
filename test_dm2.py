import asyncio, json, websockets, os, time, uuid

async def test_dm():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ 认证通过 agent_id={creds["agent_id"]}')

        # 一个一个来，间隔 8 秒避免 rate limit
        bots = ['小爱', '小开', '爱泰', '小周', '泰虾']
        for name in bots:
            msg_id = str(uuid.uuid4())
            payload = {
                'type': 'message',
                'content': f'inbox测试 - 小谷发的，收到请回',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': msg_id,
                'ts': time.time(),
                'to': f'@{name}',
            }
            await ws.send(json.dumps(payload))
            print(f'📤 DM -> {name} (id={msg_id[:8]})', end='')

            # 等 ACK
            found_ack = False
            for _ in range(4):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    if mt == 'ack' and data.get('id') == msg_id:
                        found_ack = True
                        break
                except asyncio.TimeoutError:
                    break
            if found_ack:
                print(f' ✅ ACK')
            else:
                print(f' ⚠️ 未收到 ACK')

            # 等 8 秒再发下一条
            await asyncio.sleep(8)

asyncio.run(test_dm())
