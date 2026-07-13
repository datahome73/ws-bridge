"""Send !pipeline_start R109 using 小开's identity (arch bot, not PM)."""
import json, asyncio, websockets, time, base64

API_KEY = base64.b64decode('c2tfd3NfMDNiZWQ4NzgxOTNkZmZhM2JiZTU0OGZkYTRmMGQwMDc=').decode()
AGENT_ID = 'ws_3f7cdd736c1c'

WS_URL = 'wss://wsim.datahome73.cloud/ws'

async def main():
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        # Auth as 小开
        await ws.send(json.dumps({'type': 'auth', 'api_key': API_KEY}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if auth_resp.get('type') != 'auth_ok':
            print(f'❌ Auth failed: {auth_resp}')
            return
        print(f'✅ Auth: {auth_resp.get("display_name")} ({AGENT_ID})')

        # Send !pipeline_start R109 to _inbox:server
        payload = {
            'type': 'message',
            'channel': '_inbox:server',
            'content': '!pipeline_start R109',
            'agent_id': AGENT_ID,
            'id': f'msg-{int(time.time()*1000)}',
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print('📤 !pipeline_start R109 → _inbox:server (as 小开)')

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
                    print(f'\n[{i}] {mt}: {json.dumps(msg, ensure_ascii=False)[:200]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'\n[{i}] (done)')
                    break

asyncio.run(main())
