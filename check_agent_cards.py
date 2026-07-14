"""Check agent card / role mappings on the server."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'chk-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print('❌ Fail')
            return
        api_key = resp['api_key']
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name")}')
        
        # List agent cards
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!agent_card list',
        }))
        print('📤 !agent_card list')
        
        for i in range(30):
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
