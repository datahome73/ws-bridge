#!/usr/bin/env python3
"""Trigger R110 pipeline start via ws-bridge WS protocol."""
import json, asyncio, websockets, time

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    suffix = str(int(time.time()))[-6:]
    
    # Step 1: Register temp bot
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'start-r110-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        temp_id = resp.get('agent_id', '?')
        print(f'✅ Registered: {temp_id}')
    
    # Step 2: Auth + send !pipeline_start R110
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name", "?")}')
        
        # Send !pipeline_start R110
        await ws.send(json.dumps({
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R110',
        }))
        print('📤 !pipeline_start R110')
        
        # Collect replies (server may close connection after response)
        print('--- Responses ---')
        for i in range(60):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                ch = msg.get('channel', '')
                content = str(msg.get('content', ''))
                from_name = msg.get('from_name', '')
                msg_type = msg.get('type', '')
                
                if content and content != 'None':
                    print(f'[{msg_type}] {from_name} | ch={ch}')
                    print(f'  {content[:300]}')
                    print()
            except asyncio.TimeoutError:
                print('⏱️ Timeout - no more messages')
                break
            except websockets.exceptions.ConnectionClosed as e:
                print(f'🔌 Connection closed: {e.code} {e.reason}')
                # Process any remaining messages from the buffer
                break

asyncio.run(main())
