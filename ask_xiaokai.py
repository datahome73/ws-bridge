"""再问小开是否inbox里有任务"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    from ws_client import WsBridgeClient
    
    def on_msg(msg):
        content = str(msg.get('content', ''))
        ch = msg.get('channel', '')
        from_a = msg.get('from_agent', '')
        mt = msg.get('type', '')
        if content and content != 'None':
            print(f'\n📨 [{mt}] ch={ch} from={from_a}')
            print(f'  {content[:1000]}')
    
    client = WsBridgeClient(name="小谷", ws_url="wss://wsim.datahome73.cloud/ws")
    client.on_message = on_msg
    
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return
    print("✅ 小谷已连接")
    
    xiaokai_id = "ws_3f7cdd736c1c"
    
    await client.send_message(
        content="小开，你看一下你的 _inbox 收件箱，系统有没有发过一个 R109 Step 2 的任务消息给你？频道是 _inbox:ws_3f7cdd736c1c。如果有的话请回复我",
        channel=f"_inbox:{xiaokai_id}",
        to_agent=xiaokai_id,
    )
    print("📤 已问小开查收件箱")
    
    await asyncio.sleep(15)
    
    await client.disconnect()
    print("\n✅ 断开")

asyncio.run(main())
