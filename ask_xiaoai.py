"""用小谷的身份连接，给 小爱 发消息并等待回复"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    from ws_client import WsBridgeClient
    
    msgs_received = []
    
    def on_msg(msg):
        msgs_received.append(msg)
        mt = msg.get('type', '?')
        ch = msg.get('channel', '')
        content = str(msg.get('content', ''))[:600]
        from_a = msg.get('from_agent', '')
        print(f"\n📨 [RECV] type={mt} ch={ch} from={from_a}")
        if content and content != 'None':
            print(f"  {content}")
    
    client = WsBridgeClient(name="小谷", ws_url="wss://wsim.datahome73.cloud/ws")
    client.on_message = on_msg
    
    ok = await client.connect()
    if not ok:
        print("❌ 小谷连接失败")
        return
    
    print(f"✅ 小谷已连接 (agent_id={client._agent_id})")
    
    # 先试一下发消息到 _inbox:server 查管线状态
    msg_id1 = await client.send_message(
        content="!pipeline_status",
        channel="_inbox:server",
    )
    print(f"\n📤 发送 !pipeline_status 到 _inbox:server (id={msg_id1})")
    
    await asyncio.sleep(3)
    
    # 再发一条给小爱
    ai_id = "ws_c47032fa1f67"
    msg_id2 = await client.send_message(
        content="小爱，R109 管线目前什么状态？14d534d fix 部署了吗？pipeline_contexts.json 是否存在？",
        channel=f"_inbox:{ai_id}",
        to_agent=ai_id,
    )
    print(f"📤 给小爱的消息已发送 (id={msg_id2})")
    
    # 等回复
    await asyncio.sleep(8)
    
    print(f"\n=== 共收到 {len(msgs_received)} 条消息 ===")
    for m in msgs_received:
        print(f"  {json.dumps(m, ensure_ascii=False)[:200]}")
    
    await client.disconnect()
    print("\n✅ 断开连接")

asyncio.run(main())
