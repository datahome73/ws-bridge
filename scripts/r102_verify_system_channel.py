"""验证 _inbox:_system to_agent 路由（原始WS）"""
import asyncio, json, os, sys, time, uuid

MY_KEY = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))['api_key']
MY_AID = 'ws_f26e585f6479'
XIAOAI_AID = 'ws_c47032fa1f67'
WS_URL = 'wss://wsim.datahome73.cloud/ws'
received = []
start = time.time()

async def main():
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_KEY, "agent_id": MY_AID}))
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert r['type'] == 'auth_ok', f'auth failed: {r}'
        print('✅ 已认证')

        async def reader():
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    msg = json.loads(raw)
                    t = time.time() - start
                    fn, fa, c, ch = msg.get('from_name','?'), (msg.get('from_agent','') or '')[:12], msg.get('content',''), msg.get('channel','')
                    print(f"\n  [{t:4.1f}s] {fn}({fa}) ch={ch}")
                    if c: print(f"  {c[:200]}")
                    received.append(msg)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        asyncio.create_task(reader())
        await asyncio.sleep(1)

        # 发到 _inbox:_system + to_agent 顶层
        print('\n─── _inbox:_system + to_agent=小爱 ───')
        await ws.send(json.dumps({
            "type": "message",
            "content": "【_inbox:_system 测试】收到请回 收到 ✅",
            "from_name": "小谷",
            "agent_id": MY_AID,
            "to_agent": XIAOAI_AID,
            "channel": "_inbox:_system",
            "id": str(uuid.uuid4()),
            "ts": time.time(),
        }))
        print('✅ 已发送')

        deadline = time.time() + 30
        while time.time() < deadline:
            await asyncio.sleep(1)
            for m in received:
                c, fn = m.get('content',''), m.get('from_name','')
                if '收到' in c and '✅' in c:
                    print(f'\n✅ 小爱回复！发件人="{fn}"')
                    print('   ✅ _inbox:_system 路由成功' if fn == '系统' else '   ⚠️ 直传')
                    break
            else:
                continue
            break
        else:
            print('\n⏰ 超时（小爱可能离线）')

        print(f'\n📦 {len(received)} 条')
        for m in received:
            print(f'  {m.get("from_name","?")}: {m.get("content","?")[:100]}')

asyncio.run(main())
