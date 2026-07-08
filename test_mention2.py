import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        await asyncio.sleep(15)

        # 📋点名 格式 — 会广播到大厅
        payload = {
            'type': 'message',
            'content': '📋点名 小爱 inbox测试 - 收到请回复',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 发了 "📋点名 小爱 inbox测试"')

        for i in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    print(f'📩 [{i}s] 广播 [{data.get("from_name","?")}]: {data.get("content","")[:200]}')
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
