"""Send !pipeline_start to ws-bridge and log all responses."""
import asyncio
import sys
import os
import json

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client",
    "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)

WsBridgeClient = ws_client.WsBridgeClient
load_creds = ws_client.load_creds

received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ Credentials: {name} / {creds['agent_id'][:16]}...")

    def on_message(msg):
        received_messages.append(msg)
        print(f"  << {json.dumps(msg, ensure_ascii=False)[:200]}")

    client = WsBridgeClient(
        name=name,
        api_key=creds["api_key"],
        agent_id=creds["agent_id"],
        auto_reconnect=False,
        on_message=on_message,
    )

    connected = await client.connect()
    if not connected:
        print("❌ Connect failed")
        return

    print("✅ Connected!")

    # Try sending to lobby first
    print("\n--- Sending: !pipeline_start to lobby ---")
    msg_id = await client.send_message("!pipeline_start", channel="lobby")
    if msg_id:
        print(f"✅ Sent lobby! msg_id={msg_id[:16]}")
    else:
        print("❌ No ACK for lobby")

    await asyncio.sleep(2)

    # Also try sending to _inbox:server
    print("\n--- Sending: !pipeline_start to _inbox:server ---")
    msg_id2 = await client.send_message("!pipeline_start", channel="_inbox:server")
    if msg_id2:
        print(f"✅ Sent _inbox:server! msg_id={msg_id2[:16]}")
    else:
        print("❌ No ACK for _inbox:server")

    await asyncio.sleep(2)

    # Check pipeline status
    print("\n--- Checking: !pipeline_status ---")
    msg_id3 = await client.send_message("!pipeline_status", channel="_inbox:server")
    if msg_id3:
        print(f"✅ Sent status! msg_id={msg_id3[:16]}")
    else:
        print("❌ No ACK for status")

    await asyncio.sleep(3)

    print(f"\n📦 Total received: {len(received_messages)}")
    for i, m in enumerate(received_messages):
        print(f"  [{i}] type={m.get('type')} content={str(m.get('content',''))[:120]}")

    await client.disconnect()
    print("Done.")

asyncio.run(main())
