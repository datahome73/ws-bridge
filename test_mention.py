import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth_ok, active_channel={resp.get("active_channel")}')

        # 逐个点名测试
        bots = ['@小爱', '@小开', '@爱泰', '@小周', '@泰虾']
        for target in bots:
            await asyncio.sleep(3)
            msg_id = str(uuid.uuid4())
            payload = {
                'type': 'message',
                'content': f'{target} inbox测试 - 收到请回',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': msg_id,
                'ts': time.time(),
            }
            await ws.send(json.dumps(payload))
            print(f'📤 {target} (id={msg_id[:8]})', end='')

            for _ in range(6):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    content = data.get('content', '')
                    if mt == 'ack' and data.get('id') == msg_id:
                        print(f' ✅ ACK')
                        break
                    elif mt == 'broadcast' and content:
                        print(f' 📩 广播: {content[:100]}')
                        break
                    elif mt == 'error':
                        print(f' ❌ {data.get("error","")[:60]}')
                        break
                except asyncio.TimeoutError:
                    print(f' ⏱️')
                    break

asyncio.run(test())
