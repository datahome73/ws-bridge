"""通知小开 dev 已同步"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    from ws_client import WsBridgeClient
    
    def on_msg(msg):
        content = str(msg.get('content', ''))
        ch = msg.get('channel', '')
        from_a = msg.get('from_agent', '')
        if content and content != 'None':
            print(f'\n📨 ch={ch} from={from_a}')
            print(f'  {content[:800]}')
    
    client = WsBridgeClient(name="小谷", ws_url="wss://wsim.datahome73.cloud/ws")
    client.on_message = on_msg
    
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return
    print("✅ 小谷已连接")
    
    xiaokai_id = "ws_3f7cdd736c1c"
    
    await client.send_message(
        content=(
            "小开，dev 已同步 main，包含所有 R109 commits 和你的技术方案，已推送 origin/dev (f5c6027)。"
            "你现在可以 git pull origin dev 了。拉到后开始 Step 3 编码实现。"
        ),
        channel=f"_inbox:{xiaokai_id}",
        to_agent=xiaokai_id,
    )
    print("📤 已通知小开")
    
    await asyncio.sleep(8)
    await client.disconnect()

asyncio.run(main())
