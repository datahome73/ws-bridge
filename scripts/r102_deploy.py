"""通知小爱部署"""
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
        '小爱，部署一下。\n'
        'main 最新 commit `8c161df`，改动是 _handle_server_relay 同时支持 '
        '_inbox:server 和 _inbox:_system 两个频道。\n\n'
        'pull + 重启就行：\n'
        '  git pull origin main\n'
        '  docker stop ws-bridge && docker rm ws-bridge\n'
        '  docker build -t ws-bridge:latest .\n'
        '  docker run -d --name ws-bridge --restart unless-stopped \\\n'
        '    -p 8765:8765 -p 8766:8766 \\\n'
        '    -v ws_data:/app/data \\\n'
        '    -e DISPATCH_SENDER_ID=ws_f26e585f6479 \\\n'
        '    -e WS_HTTP_PORT=8766 \\\n'
        '    ws-bridge:latest\n\n'
        '部署完回 已完成 ✅'
    )
    await client.send_message(msg, channel=f'_inbox:{XIAOAI_AID}')
    print('📨 已通知小爱部署')
    
    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(2)
    
    for m in received:
        if '已完成' in m.get('content','') and '✅' in m.get('content',''):
            print('\n✅ 小爱确认部署完成')
            break
    else:
        print('\n⏰ 小爱可能还在部署中')
    
    await client.disconnect()

asyncio.run(main())
