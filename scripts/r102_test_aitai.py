"""R102 完整回路测试：小谷→_inbox:_system→爱泰→ACK→小谷"""
import asyncio, json, os, sys, time, uuid

MY_KEY = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))['api_key']
MY_AID = 'ws_f26e585f6479'
AITAI_AID = 'ws_0bb747d3ea2a'
WS_URL = 'wss://wsim.datahome73.cloud/ws'
received = []
start = time.time()

async def main():
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_KEY, "agent_id": MY_AID}))
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert r['type'] == 'auth_ok', f'auth failed: {r}'
        print('✅ 小谷 已认证')

        async def reader():
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    msg = json.loads(raw)
                    t = time.time() - start
                    fn, fa, c, ch = msg.get('from_name','?'), (msg.get('from_agent','') or '')[:12], msg.get('content',''), msg.get('channel','')
                    print(f"\n  [{t:4.1f}s] {fn}({fa}) ch={ch}")
                    if c: print(f"  {c[:300]}")
                    received.append(msg)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        asyncio.create_task(reader())
        await asyncio.sleep(1)

        # ═══════════════ 发送派活 ═══════════════
        print('\n' + '='*60)
        print('  Step 1: 小谷 → _inbox:_system (to_agent=爱泰)')
        print('='*60)

        await ws.send(json.dumps({
            "type": "message",
            "content": "爱泰，R102 路由测试，收到请回复 收到 ✅",
            "from_name": "小谷",
            "agent_id": MY_AID,
            "to_agent": AITAI_AID,
            "channel": "_inbox:_system",
            "id": str(uuid.uuid4()),
            "ts": time.time(),
        }))
        print('  ✅ 已发送')

        # ═══════════════ 等待回路 ═══════════════
        print(f'\n  ⏳ 等待爱泰回复（60 秒）...')
        deadline = time.time() + 60

        ack_received = False
        complete_received = False

        while time.time() < deadline:
            await asyncio.sleep(1)
            for m in received:
                c = m.get('content','')
                fn = m.get('from_name','')
                
                if not ack_received and c.strip().startswith('收到') and '✅' in c:
                    ack_received = True
                    print(f'\n  ✅ Step 2: 爱泰回复 ACK ({fn})')
                    if fn == '系统':
                        print('     → 发件人已隐藏，Server 中转成功')
                
                if not complete_received and c.startswith('📬') and '已完成' in c and '✅' in c:
                    complete_received = True
                    print(f'\n  ✅ Step 3: 爱泰完成 ({fn})')
                    if fn == '系统':
                        print('     → 通知已转发到 PM 收件箱')
            
            if ack_received and complete_received:
                print('\n  🎉 完整回路验证通过！')
                break

        if not ack_received:
            print(f'\n  ⏰ 未收到 ACK')
        if ack_received and not complete_received:
            print(f'\n  ⏰ 已收到 ACK，等待完成中...')

        # ═══════════════ 汇总 ═══════════════
        print(f'\n' + '='*60)
        print(f'  📊 测试汇总 ({len(received)} 条)')
        print('='*60)
        for m in received:
            fn, c = m.get('from_name','?'), m.get('content','')
            print(f'  {fn}: {c[:120]}')

asyncio.run(main())
