"""Send !pipeline_start R109 via temp bot."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Register
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'ps-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        print(f'✅ Registered: {resp.get("agent_id")}')
    
    # Auth + send
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R109',
        }))
        print('📤 !pipeline_start R109 → _inbox:server')
        
        # Collect replies
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                error = msg.get('error', '')
                if content and content != 'None':
                    print(f'\n[{i}] ch={ch}')
                    print(f'  {content[:2000]}')
                elif error:
                    print(f'\n[{i}] ERROR: {error[:300]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'\n[{i}] (done)')
                    break
            except websockets.exceptions.ConnectionClosed:
                print(f'\n[{i}] Closed')
                break

asyncio.run(main())
