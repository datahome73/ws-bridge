"""Report R10 completion to workgroup."""
import asyncio, json, websockets
import os

WS_URL = os.environ.get('WS_BRIDGE_URL')
AGENT_ID = os.environ.get('WS_BRIDGE_AGENT_ID')
APP_ID = os.environ.get('WS_BRIDGE_APP_ID', 'ws-bridge')


async def go():
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "auth",
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "target": "ws_bridge_group"
        }))
        ack = await asyncio.wait_for(ws.recv(), timeout=5)

        content = (
            "@admin-bot R10 Step 3 编码已完成 ✅\n\n"
            "P1 令牌机制 ✅ — TokenRing dataclass + 发言权限校验 + 管理员API "
            "(set_mode/set_order/advance/skip/status)，全服务端实现，bot 无感\n"
            "P2 修复 ✅ — ws_client.py aiohttp 导入保护\n"
            "P0 适配器 ✅ — dev 分支已含 channel 路由修复，已验证完成\n\n"
            "test_workspace.py 21/21 ✅ 全部通过\n"
            "已推送到 dev\n\n"
            "需要部署 ws-bridge server（Railway）使 token-ring 生效"
        )

        msg = json.dumps({
            "type": "message",
            "channel": "lobby",
            "from": os.environ.get("WS_BRIDGE_BOT_NAME", "dev-bot"),
            "content": content,
        })
        await ws.send(msg)
        resp = await asyncio.wait_for(ws.recv(), timeout=5)
        print("Report sent, response:", resp)


asyncio.run(go())
