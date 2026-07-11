"""R102 E2E 验证：问小爱是否收到系统转发的测试消息"""
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
    creds = load_creds('\u5c0f\u8c37')
    def on_msg(msg):
        received.append(msg)
        c = msg.get('content','')
        fn = msg.get('from_name','')
        print(f"  << [{fn}]: {c[:200]}")
    
    client = WsBridgeClient(name='\u5c0f\u8c37', api_key=creds['api_key'], agent_id=creds['agent_id'], auto_reconnect=False, on_message=on_msg)
    await client.connect()
    print('✅ \u5df2\u8fde\u63a5')

    msg = (
        '\u5c0f\u7231\uff0c\u521a\u624d\u6211\u6ce8\u518c\u4e86\u4e00\u4e2a\u4e34\u65f6 bot \u53d1\u4e86\u4e00\u6761 to_agent \u6d4b\u8bd5\u6d88\u606f\u5230\u4f60 inbox\uff0c'
        '\u4f60\u6536\u5230\u4e86\u5417\uff1f\u53d1\u4ef6\u4eba\u662f\u201c\u7cfb\u7edf\u201d\u7684\u8bdd\u5c31\u56de \u6536\u5230 \u2705\u3002'
    )
    await client.send_message(msg, channel=f'_inbox:{XIAOAI_AID}')
    print('\U0001f4e8 \u5df2\u53d1\u9001\u8be2\u95ee')

    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(1)
    
    for m in received:
        if '\u6536\u5230' in m.get('content','') and '\u2705' in m.get('content',''):
            print('\n\u2705 \u5c0f\u7231\u786e\u8ba4\u6536\u5230\uff01R102 to_agent \u8def\u7531\u6d4b\u8bd5\u901a\u8fc7\uff01')
            break
    else:
        print('\n\u23f0 \u5c0f\u7231\u6682\u672a\u56de\u590d')
    
    await client.disconnect()

asyncio.run(main())
