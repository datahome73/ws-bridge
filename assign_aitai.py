"""手动派活给爱泰 — Step 3 编码实现"""
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
            print(f'  {content[:1000]}')
    
    client = WsBridgeClient(name="小谷", ws_url="wss://wsim.datahome73.cloud/ws")
    client.on_message = on_msg
    
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return
    print("✅ 小谷已连接")
    
    aitai_id = "ws_0bb747d3ea2a"
    
    msg = (
        "🏗️ **R109 Step 3 — 编码实现**\n\n"
        "需求：架构大重构，将 server/ 拆分为 ws-server/ 和 web-ui/，"
        "WSS 与 Web 完全分离，仅通过 data/ 目录关联。\n\n"
        "参考文档：\n"
        "1. 需求文档：https://github.com/datahome73/ws-bridge/blob/main/docs/R109/R109-product-requirements.md\n"
        "2. 技术方案（小开已出）：https://github.com/datahome73/ws-bridge/blob/dev/docs/R109/r109-step2-tech-plan.md\n\n"
        "当前 dev 分支已同步 main（f5c6027），包含所有 R109 文档和配置。\n"
        "请按技术方案实现，产出推 dev 分支。完成后回复 ✅ 完成"
    )
    
    await client.send_message(
        content=msg,
        channel=f"_inbox:{aitai_id}",
        to_agent=aitai_id,
    )
    print("📤 已派活给爱泰")
    
    await asyncio.sleep(8)
    
    await client.disconnect()

asyncio.run(main())
