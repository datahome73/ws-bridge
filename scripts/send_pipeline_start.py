"""Send !pipeline_start to ws-bridge server via 小谷 credentials."""
import asyncio
import sys
import os

# Import ws_client directly (skip __init__.py which has missing imports)
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

async def main():
    # Check if credentials exist
    name = "小谷"
    creds = load_creds(name)
    print(f"Loaded credentials for: {name}")
    print(f"  agent_id: {creds.get('agent_id', '')[:16]}...")

    client = WsBridgeClient(
        name=name,
        api_key=creds.get("api_key"),
        agent_id=creds.get("agent_id"),
        auto_reconnect=False,
    )

    connected = await client.connect()
    if not connected:
        print("❌ Failed to connect")
        sys.exit(1)

    print("✅ Connected, sending !pipeline_start...")

    # Send to lobby channel for normal command routing
    msg_id = await client.send_message("!pipeline_start", channel="lobby")
    if msg_id:
        print(f"✅ !pipeline_start sent (msg_id={msg_id[:16]}...)")
    else:
        print("❌ Failed to send !pipeline_start (no ACK)")

    # Wait a bit for any response
    await asyncio.sleep(3)
    await client.disconnect()
    print("Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
