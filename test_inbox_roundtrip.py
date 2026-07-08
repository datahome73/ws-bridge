#!/usr/bin/env python3
"""Inbox 完整收发测试 — 双连接验证"""
import asyncio, json, websockets, os, time, uuid

BOTS = {
    "小开": ("ws_f8a816527f9e", "~/.ws-bridge/小开.json"),
    "爱泰": ("ws_0ee70be2d59e", "~/.ws-bridge/爱泰.json"),
    "小周": ("ws_4e1a1b3ba0b9", "~/.ws-bridge/小周.json"),
    "泰虾": ("ws_cd771242975a", "~/.ws-bridge/泰虾.json"),
    "小爱": ("ws_7f0e931af04b", "~/.ws-bridge/小爱.json"),
}

async def bot_listener(name, creds_path, inbox_msgs):
    """连接为目标bot，监听收件箱消息"""
    creds = json.load(open(os.path.expanduser(creds_path)))
    try:
        async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
            await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp.get('type') == 'auth_ok'
            inbox_msgs[name] = f"✅ 已连接 agent_id={creds['agent_id']}"
            
            # 等 30 秒收 inbox
            for _ in range(20):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    data = json.loads(msg)
                    mt = data.get('type', '')
                    channel = data.get('channel', '')
                    fn = data.get('from_name', '?')
                    ct = data.get('content', '')
                    if mt == 'broadcast' and channel.startswith('_inbox:'):
                        inbox_msgs[name] = f"✅ 收到收件箱消息! 来自={fn}: {ct[:100]}"
                    elif mt == 'broadcast':
                        pass  # non-inbox broadcast
                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        inbox_msgs[name] = f"❌ 连接失败: {e}"

async def sender():
    """小谷发 inbox 消息"""
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        
        # 等 bot listeners 全部就绪
        await asyncio.sleep(3)
        
        print("=" * 60)
        print(f"📤 小谷 (PM) 发送 inbox 消息")
        print("=" * 60)
        
        for name, (agent_id, _) in BOTS.items():
            inbox_ch = f"_inbox:{agent_id}"
            await asyncio.sleep(2)
            
            payload = {
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 inbox测试 - 来自小谷，{name}收到请回 @小谷',
                'from_name': '小谷', 'agent_id': creds['agent_id'],
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }
            await ws.send(json.dumps(payload))
            
            for _ in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    if data.get('type') == 'ack':
                        sent = data.get('sent', 0)
                        print(f"📤 [{name}] → {inbox_ch}  ACK sent={sent}")
                        break
                    elif data.get('type') == 'error':
                        print(f"📤 [{name}] ❌ {data.get('error')}")
                        break
                except asyncio.TimeoutError:
                    break
        
        print(f"\n📤 所有 inbox 消息已发，等待 bot 监听结果...")
        await asyncio.sleep(5)

async def main():
    inbox_msgs = {}
    
    # 同时启动 bot 监听 + 小谷发送
    tasks = []
    for name, (_, cred_path) in BOTS.items():
        tasks.append(bot_listener(name, cred_path, inbox_msgs))
    tasks.append(sender())
    
    await asyncio.gather(*tasks)
    
    print("\n" + "=" * 60)
    print("📊 结果汇总")
    print("=" * 60)
    all_ok = True
    for name in BOTS:
        result = inbox_msgs.get(name, "⚠️ 无结果")
        if "收到收件箱消息" in result:
            print(f"  ✅ {name}: {result}")
        else:
            print(f"  {'❌' if '❌' in result else '⚠️'} {name}: {result}")
            if '❌' in result:
                all_ok = False
    print()
    if all_ok:
        print("🎉 inbox 收发全部正常!")
    else:
        print("⚠️ 有异常需要排查")

asyncio.run(main())
