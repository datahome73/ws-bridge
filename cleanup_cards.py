import asyncio, json, websockets, os, time

async def cleanup():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f'✅ 认证通过 agent_id={creds["agent_id"]}')

        # 列出所有旧 agent_id（来自旧配置）
        old_ids = ['pm-bot', 'admin-bot', 'arch-bot', 'dev-bot', 'review-bot', 'qa-bot']
        
        for old_id in old_ids:
            payload = {
                'type': 'message',
                'content': f'!agent_card unset {old_id}',
                'from_name': '小谷',
                'agent_id': creds['agent_id'],
                'id': f'unset-{old_id}-' + str(int(time.time())),
                'ts': time.time(),
            }
            await ws.send(json.dumps(payload))
            print(f'📤 发送 unset {old_id}...')
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(resp)
                content = data.get('content', str(data))
                print(f'📩 {old_id}: {content[:200]}')
            except asyncio.TimeoutError:
                print(f'⏱️ {old_id}: 超时')
            await asyncio.sleep(0.5)

        # 小开的无名卡
        payload = {
            'type': 'message',
            'content': '!agent_card unset ws_3f7cdd736',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': 'unset-nameless-' + str(int(time.time())),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 发送 unset ws_3f7cdd736...')
        try:
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(resp)
            content = data.get('content', str(data))
            print(f'📩 ws_3f7cdd736: {content[:200]}')
        except asyncio.TimeoutError:
            print('⏱️ ws_3f7cdd736: 超时')

        # 再查一次剩余卡片
        await asyncio.sleep(1)
        payload2 = {
            'type': 'message',
            'content': '!agent_card list',
            'from_name': '小谷',
            'agent_id': creds['agent_id'],
            'id': 'list-after-' + str(int(time.time())),
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload2))
        print('\n📋 清理后卡片列表：')
        for i in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'content' in data:
                    print(data['content'])
                else:
                    print(f'[{i}] {str(data)[:300]}')
            except asyncio.TimeoutError:
                break

asyncio.run(cleanup())
