"""问小爱管线状态"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    from ws_client import WsBridgeClient
    
    inbox_msgs = []
    
    def on_msg(msg):
        inbox_msgs.append(msg)
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
    
    # 问小爱管线状态
    ai_id = "ws_c47032fa1f67"
    msg_id = await client.send_message(
        content="小爱，R109 pipeline 启动了吗？你现在回复我就行",
        channel=f"_inbox:{ai_id}",
        to_agent=ai_id,
    )
    print(f"📤 已问小爱 (msg_id={msg_id})")
    
    # 多等一会儿等回复
    await asyncio.sleep(15)
    
    print(f"\n=== 共收到 {len(inbox_msgs)} 条消息 ===")
    
    await client.disconnect()

asyncio.run(main())
