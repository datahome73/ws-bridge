"""Test Fix 2: step_complete with --summary."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

msgs = []
def on_message(msg):
    msgs.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    ts = msg.get('ts', 0)
    if ts > 1:  # live msgs only
        print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='t', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(6)
    msgs.clear()

    # Advance pipeline via handoff to step5
    print('=== Handoff step2->step5 ===')
    for step, summary in [('step2', '验证范围'), ('step3', 'Dev确认'), ('step4', '审查通过')]:
        await client.send_message(f'!step_handoff {step} --output b3ed0cd --summary {summary}')
        await asyncio.sleep(6)

    # NOW test step_complete (was broken before Fix 2)
    print('\n=== STEP_COMPLETE FIX 2 TEST ===')
    await client.send_message('!step_complete step5 --output b3ed0cd --summary "R70多角色全链路验证通过" --artifact-url https://github.com/datahome73/ws-bridge')
    await asyncio.sleep(7)

    print('\n--- Check for errors ---')
    for m in msgs:
        c = m.get('content', '')
        if '执行失败' in c and 'step_config' in c:
            print(f'  ❌ Fix 2 FAILED: {c[:200]}')

    has_step_config_err = any('执行失败' in m.get('content','') and 'step_config' in m.get('content','') for m in msgs)
    print(f'\nFix 2 (step_complete scope): {"✅" if not has_step_config_err else "❌ STILL BROKEN"}')

    await client.disconnect()

asyncio.run(main())
