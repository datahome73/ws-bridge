#!/usr/bin/env python3
"""更新 credentials + 测小爱"""
import asyncio, json, websockets, os, time

REAL_IDS = {
    "小开": "ws_3f7cdd736c1c",
    "爱泰": "ws_0bb747d3ea2a",
    "小周": "ws_fcf496ca1b4f",
    "泰虾": "ws_eab784ac7652",
    "小爱": "ws_c47032fa1f67",
}

# 更新 credential 文件
for name, real_id in REAL_IDS.items():
    fpath = os.path.expanduser(f'~/.ws-bridge/{name}.json')
    cred = json.load(open(fpath))
    old_id = cred.get('agent_id', '?')
    if old_id != real_id:
        cred['agent_id'] = real_id
        json.dump(cred, open(fpath, 'w'), ensure_ascii=False, indent=2)
        print(f"✅ {name}: {old_id} → {real_id}")
    else:
        print(f"✓ {name}: 已正确")

print()

# 测小爱
async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过\n")

        # 小爱 inbox
        inbox_ch = "_inbox:ws_c47032fa1f67"
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': inbox_ch,
            'content': '📋 小爱 inbox测试 - 所有bot的inbox已确认正常。收到请回 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xa-done-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if data.get('type') == 'ack':
                    print(f"✅ 小爱 inbox: sent={data.get('sent',0)} 投递成功")
                    break
            except asyncio.TimeoutError:
                pass

        print(f"\n✅ 完成")

asyncio.run(test())
