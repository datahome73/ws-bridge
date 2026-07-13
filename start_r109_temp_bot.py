"""Register temp bot → auth → !pipeline_start R109 from _inbox:server upstream."""
import json, asyncio, websockets, time, base64

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Step 1: Register
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'p109-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        agent_id = resp['agent_id']
        print(f'✅ Registered: {agent_id} / api_key={api_key}')
    
    # Step 2: Auth + send
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("type")} — {auth_resp.get("display_name")}')
        
        if auth_resp.get('type') != 'auth_ok':
            print(f'❌ Auth failed')
            return
        
        # Send !pipeline_start R109
        payload = {
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R109',
        }
        await ws.send(json.dumps(payload))
        print('📤 !pipeline_start R109 → _inbox:server')
        
        # Collect replies
        for i in range(30):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                mt = msg.get('type', '?')
                ch = msg.get('channel', '')
                content = str(msg.get('content', ''))
                from_agent = msg.get('from_agent', '')
                error = msg.get('error', '')
                
                if content and content != 'None':
                    print(f'\n[{i}] {mt} ch={ch} from={from_agent}')
                    print(f'  {content[:1500]}')
                elif error:
                    print(f'\n[{i}] ERROR: {error[:300]}')
                else:
                    print(f'\n[{i}] {mt} {json.dumps(msg, ensure_ascii=False)[:200]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'\n[{i}] (done)')
                    break
    
    print('\n=== DONE ===')

asyncio.run(main())
