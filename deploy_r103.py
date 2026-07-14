"""Send R103 deploy request to 小爱 via inbox."""
import asyncio, json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'clients', 'python'))
from ws_client import WsBridgeClient

async def main():
    client = WsBridgeClient(
        name="小谷",
        ws_url="wss://wsim.datahome73.cloud/ws",
    )
    ok = await client.connect()
    if not ok:
        print("ERROR: connect failed")
        return

    AI_ID = "ws_c47032fa1f67"
    task_content = (
        "【R103 部署】小爱，R103 Step 4 审查通过 ✅，"
        "已合并到 main (404d39a)。\n"
        "前端 templates.py 有改动，需重建 Docker 镜像部署。"
    )

    msg_id = await client.send_message(
        content=task_content,
        channel=f"_inbox:{AI_ID}",
    )
    print(f"Deploy request sent to 小爱, msg_id={msg_id}")

    await client.disconnect()

asyncio.run(main())
