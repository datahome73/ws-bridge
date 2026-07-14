"""派活给泰虾 — Step 5 测试验证"""
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
    
    taixia_id = "ws_eab784ac7652"
    
    msg = (
        "🦐 **R109 Step 5 — 测试验证**\n\n"
        "编码（爱泰）和审查（小周）已完成，代码在 dev 分支。\n\n"
        "需求文档：https://github.com/datahome73/ws-bridge/blob/main/docs/R109/R109-product-requirements.md\n\n"
        "验收项重点：\n"
        "1. ws-server/ 和 web-ui/ 零 import 依赖\n"
        "2. Web 只剩收件箱+历史两个 Tab\n"
        "3. shared/ 目录已删除，各模块独立 auth/message_store/persistence\n"
        "4. config.py 已精简\n"
        "5. bot 状态通过文件传递（非 HTTP 轮询）\n\n"
        "当前 dev 分支已包含所有改动。请测试后出测试报告，完成后回复 ✅ 完成"
    )
    
    await client.send_message(
        content=msg,
        channel=f"_inbox:{taixia_id}",
        to_agent=taixia_id,
    )
    print("📤 已派活给泰虾")
    
    await asyncio.sleep(8)
    await client.disconnect()

asyncio.run(main())
