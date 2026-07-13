"""Send Step 1 completion to advance R109 pipeline."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Register temp bot
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'adv-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        print(f'✅ Registered: {resp.get("agent_id")}')
    
    # Auth + send completion + query status
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        # Step 1: Mark Step 1 complete
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '已完成 ✅ R109 Step 1 — 需求文档审核通过，auto_chain 推进',
        }))
        print('📤 已完成 ✅ R109 Step 1')
        
        # Wait a few seconds for auto_chain to process
        await asyncio.sleep(3)
        
        # Step 2: Query pipeline status
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status')
        
        # Collect all replies
        for i in range(25):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                error = msg.get('error', '')
                
                if content and content != 'None':
                    print(f'\n[{i}] ch={ch}')
                    print(f'  {content[:3000]}')
                elif error:
                    print(f'\n[{i}] ERROR: {error[:300]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'[{i}] (done)')
                    break
            except websockets.exceptions.ConnectionClosed:
                print(f'[{i}] Connection closed')
                break

asyncio.run(main())
