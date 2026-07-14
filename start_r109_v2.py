"""Send !pipeline_start R109 to _inbox:server via raw WebSocket."""
import json, asyncio, websockets, time

with open('/opt/data/home/.ws-bridge/小谷.json') as f:
    creds = json.load(f)

API_KEY = creds['api_key']
MY_AID = creds['agent_id']

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        # Auth
        await ws.send(json.dumps({'type': 'auth', 'api_key': API_KEY}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if auth_resp.get('type') != 'auth_ok':
            print(f'❌ Auth failed: {auth_resp}')
            return
        print(f'✅ Auth: {auth_resp.get("display_name")}')

        # Send !pipeline_start R109 to _inbox:server
        payload = {
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R109',
            'agent_id': MY_AID,
            'id': f'msg-{int(time.time()*1000)}',
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 !pipeline_start R109 → _inbox:server')

        # Collect replies
        for i in range(20):
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
                    print(f'\n[{i}] {mt}: {json.dumps(msg, ensure_ascii=False)[:200]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'\n[{i}] (done, no more messages)')
                    break
                continue

asyncio.run(main())
