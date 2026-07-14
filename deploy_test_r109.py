"""Full test: !pipeline_start R109 → complete Step 1 → check auto_dispatch."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Register temp bot
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'test-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register fail')
            return
        api_key = resp['api_key']
        print(f'✅ Registered')
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        # Step 1: !pipeline_start R109
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R109',
        }))
        print('\n📤 !pipeline_start R109')
        await asyncio.sleep(2)
        
        # Step 2: Complete Step 1
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '已完成 ✅ R109 Step 1 — WORK_PLAN 已审核',
        }))
        print('📤 已完成 ✅ R109 Step 1')
        await asyncio.sleep(3)
        
        # Step 3: Check pipeline status
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status\n')
        
        for i in range(30):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                mt = msg.get('type', '')
                if content and content != 'None':
                    print(f'[{i}] {mt} ch={ch}')
                    print(f'  {content[:2000]}\n')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'[{i}] done')
                    break
            except:
                break

asyncio.run(main())
