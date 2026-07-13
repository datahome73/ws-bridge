"""Send Step 1 completion for R109 and check status."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'dv-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Fail: {resp}')
            return
        api_key = resp['api_key']
        print(f'✅ Registered')
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        # Step 1: Send completion
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '已完成 ✅ R109 Step 1 — WORK_PLAN 已审核',
        }))
        print('📤 已完成 ✅ R109 Step 1')
        
        await asyncio.sleep(3)
        
        # Step 2: Check status
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status')
        
        for i in range(25):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                if content and content != 'None':
                    print(f'\n[{i}] ch={ch}')
                    print(f'  {content[:3000]}')
            except asyncio.TimeoutError:
                if i > 3:
                    break
            except:
                break

asyncio.run(main())
