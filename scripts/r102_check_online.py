"""检查小爱是否在线"""
import asyncio, json, os, sys, time
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location('ws_client', 'clients/python/ws_client.py')
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
WsBridgeClient, load_creds = ws_client.WsBridgeClient, ws_client.load_creds

received = []

async def main():
    creds = load_creds('小谷')
    def on_msg(msg):
        received.append(msg)
        if msg.get('content'):
            print(f"  [{msg.get('from_name','?')}]: {msg.get('content','')[:200]}")

    client = WsBridgeClient(name='小谷', api_key=creds['api_key'], agent_id=creds['agent_id'], auto_reconnect=False, on_message=on_msg)
    await client.connect()
    print('✅ 已连接')

    # 用小谷身份直接 inbox 问小爱在不在
    await client.send_message(
        "小爱，在吗？我正在做 R102 to_agent 路由测试。收到请回 收到 ✅",
        channel=f'_inbox:{XIAOAI_AID}',
    )
    print('📨 已发直接消息给小爱')

    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(2)

    # 看看有没有自动 ACK 或状态消息
    for m in received:
        print(f'\n  消息: {json.dumps(m, ensure_ascii=False)[:200]}')

    await client.disconnect()

XIAOAI_AID = 'ws_c47032fa1f67'
asyncio.run(main())
