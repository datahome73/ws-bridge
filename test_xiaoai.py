import asyncio, json, websockets, os, time, uuid

async def test_msg():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK, channel={resp.get("active_channel")}')

        # 发消息给小爱
        msg_id = str(uuid.uuid4())
        payload = {
            'type': 'message',
            'content': '@小爱 inbox测试 - gateway 配置成功了吗？收到请回复',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id,
            'ts': time.time(),
            'to': '@小爱',
        }
        await ws.send(json.dumps(payload))
        print(f'📤 sent to @小爱 (id={msg_id[:8]})')

        # 等回音
        for i in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'ack':
                    print(f'  ✅ ACK: id={data.get("id","")[:8]}')
                elif mt == 'broadcast':
                    content = data.get('content', '')
                    from_name = data.get('from_name', '')
                    print(f'  📩 [{from_name}]: {content[:200]}')
                else:
                    print(f'  📩 type={mt}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                print(f'  ⏱️ 3s 无消息')
                break

asyncio.run(test_msg())
