"""Ask 小爱 to run !pipeline_start R109 from server-side docker exec."""
import json, asyncio, websockets, time

with open('/opt/data/home/.ws-bridge/小谷.json') as f:
    creds = json.load(f)

API_KEY = creds['api_key']
MY_AID = creds['agent_id']
MY_NAME = creds['display_name']
XIAOAI_AID = 'ws_c47032fa1f67'

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

        # Send to 小爱's inbox
        payload = {
            'type': 'message',
            'channel': f'_inbox:{XIAOAI_AID}',
            'content': '''小爱，帮我从服务器端 docker exec 执行：python3 -c "
import json, asyncio, websockets

async def start():
    async with websockets.connect('ws://localhost:8765/ws') as ws:
        import time
        suffix = str(int(time.time()))[-6:]
        await ws.send(json.dumps({'type': 'register', 'display_name': f'p109-{suffix}'}))
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        api_key = r['api_key']
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        await ws.send(json.dumps({'type': 'message', 'channel': '_inbox:server', 'content': '!pipeline_start R109'}))
        print('sent')
        await asyncio.sleep(3)

asyncio.run(start())
"

R109 不在 pipeline_contexts.json 中，需要重新发指令启动。确认执行后回复结果。''',
            'to_agent': XIAOAI_AID,
            'agent_id': MY_AID,
            'id': f'msg-{int(time.time()*1000)}',
            'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f'📤 Pipeline start request sent to 小爱 ({XIAOAI_AID})')

        # Collect replies
        for i in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                from_agent = msg.get('from_agent', '')
                if content and content != 'None':
                    print(f'\n[{i}] ch={ch} from={from_agent}')
                    print(f'  {content[:1500]}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'\n[{i}] (done)')
                    break

asyncio.run(main())
