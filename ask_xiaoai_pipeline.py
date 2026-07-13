"""再问小爱管线状态"""
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
            print(f'  {content[:1200]}')
    
    client = WsBridgeClient(name="小谷", ws_url="wss://wsim.datahome73.cloud/ws")
    client.on_message = on_msg
    
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return
    print("✅ 小谷已连接")
    
    ai_id = "ws_c47032fa1f67"
    await client.send_message(
        content="小爱，现在 pipeline_contexts.json 里 R109 的 current_step 是多少？auto dispatch 触发了吗？小开说她在看文档了",
        channel=f"_inbox:{ai_id}",
        to_agent=ai_id,
    )
    print("📤 已问")
    
    await asyncio.sleep(12)
    
    await client.disconnect()
    print("\n✅ 断开")

asyncio.run(main())
