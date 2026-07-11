"""通知小爱重新部署（修复PM消息被吞）"""
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
        '小爱，重新部署一下。\n'
        '刚才部署 `f368fd4` 有个bug——PM(小谷)的ACK ✅消息也被重定向到 '
        '_inbox:server然后被安全守卫吞掉了。已修好(b41074e)。\n\n'
        'pull + 重启：\n'
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
    print('📨 已通知小爱重新部署')

asyncio.run(main())
