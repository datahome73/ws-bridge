#!/usr/bin/env python3
"""R110 dispatch via 小谷 only (no temp bot registrations).
Step 1: !pipeline_start R110 → _admin
Step 2: Step 2 task → 小开 via _inbox:server (with to_agent)
Step 3: Step 1 completion signal → _inbox:server (triggers auto-advance)
Step 4: Verify pipeline status
"""
import json, asyncio, websockets, time, os

WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOKAI_ID = "ws_3f7cdd736c1c"
CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")

STEP2_MSG = ("🏗️ **R110 Step 2 — 技术方案**\n\n"
    "需求文档已审核通过：https://github.com/datahome73/ws-bridge/blob/main/docs/R110/R110-product-requirements.md\n\n"
    "请评估以下事项并输出技术方案文档 `docs/R110/r110-step2-tech-plan.md`:\n"
    "1. PipelineAutoStarter 组件设计\n2. from_work_plan 工厂方法\n"
    "3. 角色映射\n4. 启动方式\n5. 安全边界\n6. 与 !pipeline_start 兼容\n\n"
    "推 dev 后回复 ✅ 完成")

async def auth_as_xiaogu():
    """Auth using 小谷's existing credentials."""
    creds = json.loads(open(CRED_PATH).read())
    ws = await websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15)
    await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    print(f'✅ Auth 小谷: {resp.get("display_name")}')
    return ws

async def send_and_collect(ws, msg, label, timeout=1, max_collect=10):
    """Send one message, collect responses."""
    await ws.send(json.dumps(msg))
    print(f'📤 {label}')
    responses = []
    for _ in range(max_collect):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            responses.append(json.loads(raw))
        except asyncio.TimeoutError:
            break
        except websockets.exceptions.ConnectionClosed:
            break
    for r in responses:
        ct = str(r.get('content',''))
        err = r.get('error','')
        ch = r.get('channel','')
        fn = r.get('from_name','')
        if err: print(f'  ❌ {err}')
        if ct and ct != 'None': print(f'  [{ch}] {fn}: {ct[:200]}')
    print(f'  → {len(responses)} responses')
    return responses

async def main():
    # Step 1: !pipeline_start R110 → _admin (action command)
    print('=== Step 1: !pipeline_start R110 ===')
    ws = await auth_as_xiaogu()
    await send_and_collect(ws, {'type': 'message', 'channel': '_admin', 'content': '!pipeline_start R110'},
                           '!pipeline_start R110 → _admin', timeout=3, max_collect=15)
    await ws.close()
    await asyncio.sleep(2)

    # Step 2: Step 2 → 小开 via _inbox:server with to_agent
    print('\n=== Step 2: Step 2 → 小开 ===')
    ws = await auth_as_xiaogu()
    await send_and_collect(ws, {
        'type': 'message', 'channel': '_inbox:server',
        'to_agent': XIAOKAI_ID,
        'from_name': '小谷',
        'content': STEP2_MSG,
    }, 'Step 2 → 小开', timeout=3, max_collect=15)
    await ws.close()
    await asyncio.sleep(1)

    # Step 3: Step 1 completion signal → _inbox:server (triggers auto-advance)
    print('\n=== Step 3: Step 1 completion signal ===')
    ws = await auth_as_xiaogu()
    await send_and_collect(ws, {
        'type': 'message', 'channel': '_inbox:server',
        'content': '已完成 ✅ R110 Step 1 — 需求文档已审核，auto_chain 推进',
    }, '已完成 ✅ R110 Step 1', timeout=3, max_collect=15)
    await ws.close()
    await asyncio.sleep(1)

    # Step 4: Verify pipeline status
    print('\n=== Step 4: !pipeline_status ===')
    ws = await auth_as_xiaogu()
    await send_and_collect(ws, {
        'type': 'message', 'channel': '_inbox:server', 'content': '!pipeline_status',
    }, '!pipeline_status', timeout=3, max_collect=20)
    await ws.close()

    print('\n✅ R110 dispatch complete!')

asyncio.run(main())
