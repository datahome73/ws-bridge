import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        await asyncio.sleep(15)  # wait for rate limit

        # 直接发一条到大厅，不加 @
        payload = {
            'type': 'message',
            'content': '小爱 测试inbox - 我是小谷，收到请回复',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 发了 "小爱 测试inbox"')

        for i in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    broadcast_content = data.get('content', '')
                    from_name = data.get('from_name', '?')
                    print(f'📩 [{i}s] 广播 [{from_name}]: {broadcast_content[:200]}')
                elif mt == 'ack':
                    print(f'✅ [{i}s] ACK')
                elif mt == 'error':
                    print(f'❌ [{i}s] 错误: {data.get("error","")}')
                else:
                    print(f'📩 [{i}s] type={mt}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                pass
        print('⏹️  done')

asyncio.run(test())
