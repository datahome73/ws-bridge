"""直连透传：问小开配置修好没"""
import asyncio
import sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client", "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
WsBridgeClient, load_creds = ws_client.WsBridgeClient, ws_client.load_creds

XIAOKAI_AID = "ws_3f7cdd736c1c"
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

    await client.send_message(
        "小开，我刚发了 R102 测试任务给你，你没回复。配置改好了吗？"
        "改好的话回复 已完成 ✅",
        channel=f"_inbox:{XIAOKAI_AID}"
    )
    print('📨 已发送')

    import time
    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received:
            if '已完成' in m.get('content',''):
                print('✅ 小开确认')
                return
    print('⏰ 超时')
    await client.disconnect()

asyncio.run(main())
