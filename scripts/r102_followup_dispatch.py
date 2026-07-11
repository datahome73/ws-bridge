"""R102: 跟进小爱 — DISPATCH_SENDER_ID 配好了吗"""
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
        c = msg.get('content','')[:500]
        print(f"  << [{msg.get('from_name','?')}]: {c}")

    client = WsBridgeClient(name='小谷', api_key=creds['api_key'], agent_id=creds['agent_id'], auto_reconnect=False, on_message=on_msg)
    await client.connect()
    print('✅ 已连接')

    # 简短跟进
    content = (
        "小爱，之前说的 DISPATCH_SENDER_ID 配好了吗？\n"
        "配好了回个 已完成 ✅ 就行。"
    )
    await client.send_message(content, channel=f'_inbox:{XIAOAI_AID}')
    print('📨 跟进消息已发送')

    deadline = time.time() + 60
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received:
            c = m.get('content','')
            if '已完成' in c:
                print(f"\n✅ 小爱确认配置完成！")
                break
        else:
            continue
        break
    else:
        # 看看有没有任何回复
        for m in received[-3:]:
            print(f"  最近消息: [{m.get('from_name','?')}]: {m.get('content','')[:200]}")
        print("\n⏰ 等不到回复。不过之前他说了「我来加上」，应该已经处理了。")

    await client.disconnect()

asyncio.run(main())
