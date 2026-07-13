"""Check pipeline status to see if R109 was created."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Register
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'st-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Fail: {resp}')
            return
        api_key = resp['api_key']
    
    # Auth + status
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
        
        all_output = []
        for i in range(25):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                error = msg.get('error', '')
                if content and content != 'None':
                    all_output.append(f'[{i}] ch={ch}: {content[:3000]}')
                elif error:
                    all_output.append(f'[{i}] ERROR: {error[:300]}')
            except asyncio.TimeoutError:
                if i > 3:
                    break
            except websockets.exceptions.ConnectionClosed:
                break
        
        for line in all_output:
            print(line)
        if not all_output:
            print("(no response)")

asyncio.run(main())
