"""通知小爱重新部署（加 '✅ ' 通用前缀）"""
import asyncio, json, os, sys, time
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location('ws_client', 'clients/python/ws_client.py')
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
WsBridgeClient, load_creds = ws_client.WsBridgeClient, ws_client.load_creds

XIAOAI_AID = 'ws_c47032fa1f67'
received = []

async def main():
    creds = load_creds('小谷')
    def on_msg(msg):
        received.append(msg)
        c = msg.get('content','')
        fn = msg.get('from_name','')
        print(f"  << [{fn}]: {c[:200]}")
    
    client = WsBridgeClient(name='小谷', api_key=creds['api_key'], agent_id=creds['agent_id'], auto_reconnect=False, on_message=on_msg)
    await client.connect()
    print('✅ 已连接')
    
    msg = (
        '小爱，再部署一次。\n'
        'main 最新 commit `41c6bba`，加了通用前缀 "✅ "——'
        '之前 "✅ R102 部署完成" 这种消息因为开头不是 "✅ 完成" 没命中前缀，'
        '仍然走了 _system。现在只要是 ✅ 开头就强制走 _inbox:server。\n\n'
        'pull + 重启：\n'
        '  git pull origin main\n'
        '  docker stop ws-bridge && docker rm ws-bridge\n'
        '  docker build -t ws-bridge:latest .\n'
        '  docker run -d --name ws-bridge --restart unless-stopped \\\n'
        '    -p 8765:8765 -p 8766:8766 \\\n'
        '    -v ws_data:/app/data \\\n'
        "    --env-file /opt/ws-bridge/.env \\\n"
        '    ws-bridge:latest\n\n'
        '部署完回 已完成 ✅'
    )
    await client.send_message(msg, channel=f'_inbox:{XIAOAI_AID}')
    print('📨 已通知小爱重新部署')

asyncio.run(main())
