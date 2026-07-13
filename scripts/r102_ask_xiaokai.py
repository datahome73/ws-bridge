"""直连问小开"""
import asyncio, sys, time
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location('ws_client', '/opt/data/ws-bridge/clients/python/ws_client.py')
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
WsBridgeClient, load_creds = ws_client.WsBridgeClient, ws_client.load_creds

received = []
async def main():
    creds = load_creds('小谷')
    def on_msg(msg):
        received.append(msg)
        print(f"  << [{msg.get('from_name','?')}]: {msg.get('content','')[:200]}")
    client = WsBridgeClient(name='小谷', api_key=creds['api_key'], agent_id=creds['agent_id'], auto_reconnect=False, on_message=on_msg)
    await client.connect()
    print('✅ 已连接')
    await client.send_message("小开，我刚通过 _inbox:server 发了一个任务给你，你收到了吗？回一下 已完成 ✅", channel="_inbox:ws_3f7cdd736c1c")
    print('📨 已发送')
    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received:
            if '已完成' in m.get('content',''):
                print('✅ 小开回了')
                return
    print('⏰ 超时')
asyncio.run(main())
