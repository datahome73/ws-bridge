#!/usr/bin/env python3
"""通过 inbox 给小开派活 R100 Step 2"""
import json, asyncio, websockets

creds = json.load(open('/opt/data/home/.ws-bridge/小谷.json'))

async def send():
    async with websockets.connect("wss://wsim.datahome73.cloud/ws") as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": creds["api_key"]}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok", f"auth failed: {resp}"

        content = (
            "【R100 Step 2 任务 — 架构设计方案 🎯】\n\n"
            "角色: architect\n\n"
            "参考文档:\n"
            "1. 需求文档: https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/R100-product-requirements.md\n"
            "2. 当前架构全景: https://raw.githubusercontent.com/datahome73/ws-bridge/dev/server/README.md\n"
            "3. 工作计划: https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/WORK_PLAN.md\n\n"
            "任务:\n"
            "产出 docs/R100/R100-tech-plan.md，包含:\n"
            "- 8 个新文件的定位和边界确认\n"
            "- 依赖关系（确保无循环导入）\n"
            "- 核心/插件边界划分\n"
            "- Step 3 编码的执行建议\n\n"
            "完成后请推 dev 分支，并在 _inbox:server 回复 ✅ 完成，告知 commit SHA。"
        )

        payload = {
            "type": "message",
            "channel": "_inbox:ws_3f7cdd736c1c",
            "content": content,
            "from_name": "小谷(PM)",
            "agent_id": creds["agent_id"],
        }
        await ws.send(json.dumps(payload))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f"ack: type={ack.get('type')} sent={ack.get('sent')}")

asyncio.run(send())
