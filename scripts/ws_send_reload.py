"""Connect to ws-bridge server, authenticate, send !agent_card reload."""
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("需要 websockets 库: pip install websockets")
    sys.exit(1)

WS_URL = "ws://72.62.197.200:8766"

async def main():
    agent_id = sys.argv[1] if len(sys.argv) > 1 else input("agent_id: ")
    app_id = sys.argv[2] if len(sys.argv) > 2 else input("app_id: ")

    print(f"Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL) as ws:
        # 1. Authenticate
        auth = {"type": "auth", "agent_id": agent_id, "app_id": app_id}
        print(f">>> {json.dumps(auth)}")
        await ws.send(json.dumps(auth))

        # 2. Read auth response
        resp = json.loads(await ws.recv())
        print(f"<<< {json.dumps(resp, ensure_ascii=False)}")
        if resp.get("type") == "auth_error" or resp.get("type") == "error":
            print("❌ 认证失败")
            return

        # 3. Send command
        msg = {"type": "message", "content": "!agent_card reload", "channel": "_admin"}
        print(f">>> {json.dumps(msg)}")
        await ws.send(json.dumps(msg))

        # 4. Wait for response(s)
        for _ in range(5):
            try:
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                print(f"<<< {json.dumps(resp, ensure_ascii=False)}")
                if resp.get("type") == "broadcast":
                    content = resp.get("content", "")
                    if "Reloaded" in content or "role map" in content:
                        print("\n✅ 命令执行成功！")
                        break
            except asyncio.TimeoutError:
                print("(等待超时)")
                break

        await ws.close()

if __name__ == "__main__":
    asyncio.run(main())
