import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ auth OK')

        await asyncio.sleep(15)

        payload = {
            'type': 'message',
            'content': '@小爱 回复测试 - 收到后用 @小谷 回复我',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': str(uuid.uuid4()),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 @小爱 已发，等回复中...')

        for i in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'broadcast':
                    from_name = data.get('from_name', '?')
                    content = data.get('content', '')
                    print(f'📩 [{i}s] [{from_name}]: {content[:200]}')
                    if '小爱' in str(from_name) or '回复' in content:
                        print('🎉 收到小爱回复！')
                        break
                elif mt == 'ack':
                    print(f'✅ [{i}s] ACK')
                elif mt == 'error':
                    print(f'❌ [{i}s] {data.get("error","")}')
                else:
                    print(f'📩 [{i}s] type={mt}: {str(data)[:200]}')
            except asyncio.TimeoutError:
                pass
        print('⏹️  done')

asyncio.run(test())
