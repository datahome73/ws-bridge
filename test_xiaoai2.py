import asyncio, json, websockets, os, time, uuid

async def test_msg():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        # 发消息 - 不加 to 字段，只用 @小爱 在 content 里
        msg_id = str(uuid.uuid4())
        payload = {
            'type': 'message',
            'content': '@小爱 我是小谷，gateway 配置测试，收到请回复',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': msg_id,
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f'📤 sent @小爱 (id={msg_id[:8]})')

        # 等 15 秒，看有没有回音
        print('📡 监听 15s...')
        for i in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    content = data.get('content', '')
                    from_name = data.get('from_name', '')
                    print(f'  📩 [{i}s] [{from_name}]: {content[:200]}')
                elif mt == 'ack':
                    print(f'  ✅ [{i}s] ACK id={data.get("id","")[:8]}')
                else:
                    print(f'  📩 [{i}s] type={mt}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                pass
        print('⏹️  结束')

asyncio.run(test_msg())
