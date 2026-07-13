"""Just query pipeline status."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'st-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status')
        
        seen = set()
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                if content and content != 'None':
                    key = content[:100]
                    if key not in seen:
                        seen.add(key)
                        print(f'\n[{i}] ch={ch}')
                        print(f'  {content[:3000]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'[{i}] (done)')
                    break
            except websockets.exceptions.ConnectionClosed:
                print(f'[{i}] Closed')
                break

asyncio.run(main())
