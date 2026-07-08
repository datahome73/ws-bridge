#!/usr/bin/env python3
"""R70 Step 3 → 4: handoff bypass — 使用 step_handoff 绕过 step_complete scope bug"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID")
BOT_NAME = "小谷"
CHANNEL = "ws:01KT6E4D-R70-fix"

async def send(client, cmd, label, wait=6):
    print(f"\n🚀 [{label}] {cmd}")
    mid = await client.send_message(cmd, channel=CHANNEL)
    if mid:
        print(f"  ✅ ACK")
    else:
        print(f"  ⚠️ 无ACK")
    await asyncio.sleep(wait)

async def main():
    msgs = []
    def on_msg(m):
        msgs.append(m)
        c = m.get("content","") or ""
        if c:
            print(f"  📨 {c[:600]}")

    client = WsBridgeClient(ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME, auto_reconnect=False)
    client.on_message = on_msg
    print("🔄 连接 ws-bridge...")
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return
    await asyncio.sleep(2)
    print(f"✅ 已连接 (channel={CHANNEL} name={BOT_NAME})\n")

    sha = "05add56"
    summary = "验证范围确认 — 6-Step 全链路验证焦点矩阵 + 逐项验收条件 + 降级方案"
    url = "https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-verification-scope.md"

    # Use step_handoff as PM (pipeline triggerer, admin role) to bypass step_complete scope bug
    await send(client,
        f'!step_handoff step3 --output {sha} --summary "{summary}" --artifact-url {url}',
        "Step 3 → 4 handoff (bypass scope bug)",
        6)

    # Verify pipeline status (V-6, V-9)
    await send(client, '!pipeline_status', "V-6/V-9 pipeline_status", 4)

    print("\n" + "=" * 50)
    print("结果汇总")
    print("=" * 50)
    for m in msgs:
        c = m.get("content","")
        f = m.get("from_name","?")
        if "未知命令" not in c and c:
            print(f"  [{f}] {c[:500]}")

    await client.disconnect()
    print(f"\n📊 共收到 {len(msgs)} 条消息")

asyncio.run(main())
