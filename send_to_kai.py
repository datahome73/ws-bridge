"""Send R102 test to 小开 and listen for replies (sync callback)."""
import asyncio, json, os, sys, uuid, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'clients/python'))
from ws_client import WsBridgeClient

received = []

def on_message(msg):
    """Sync callback — ws_client calls this without await."""
    received.append(msg)
    content = msg.get('content', '')
    sender = msg.get('from') or msg.get('agent_id') or ''
    print(f'<< from={sender}: {content[:300]}', flush=True)

async def main():
    client = WsBridgeClient(
        name='小谷',
        ws_url='wss://wsim.datahome73.cloud/ws',
        on_message=on_message,
    )
    ok = await client.connect()
    if not ok:
        print('ERROR: connect failed')
        return

    print(f'Connected as: {client.agent_id}', flush=True)

    KAI_ID = 'ws_3f7cdd736c1c'
    task_content = (
        '【R102 全流程测试】小开，现在来做一轮完整测试。请按以下步骤回复：\n\n'
        '1️⃣ 收到任务后，请回复「收到 ✅」\n'
        '2️⃣ 完成测试后，请回复「已完成 ✅ 测试通过」\n\n'
        '注意：序号「收到 ✅」必须是中文在前、对勾在后。'
    )

    # Send via R102 route: _inbox:server + to_agent
    msg_id = str(uuid.uuid4())
    payload = {
        'type': 'message',
        'content': task_content,
        'from_name': '小谷',
        'agent_id': client.agent_id,
        'id': msg_id,
        'ts': time.time(),
        'channel': '_inbox:server',
        'to_agent': KAI_ID,
    }

    async with client._ws_lock:
        if client._ws and client._authed:
            await client._ws.send(json.dumps(payload))
            print(f'Sent via _inbox:server (id={msg_id[:8]})', flush=True)
        else:
            print('ERROR: not connected', flush=True)
            return

    # Listen for up to 90 seconds for replies
    try:
        for i in range(90):
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass

    print(f'\nListener done. Total replies: {len(received)}', flush=True)
    if received:
        for i, m in enumerate(received):
            print(f'  [{i}] from={m.get("from") or m.get("agent_id","")}: {m.get("content","")[:200]}', flush=True)
    await client.disconnect()

asyncio.run(main())
