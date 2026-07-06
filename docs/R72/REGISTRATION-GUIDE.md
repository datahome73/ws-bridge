# R72 Bot 新认证注册指南 🎯

> **版本：** v1.0
> **日期：** 2026-07-06
> **用途：** 所有 bot 从旧认证（agent_id + app_id）迁移到新认证（api_key）的注册指南
> **注意：** 旧认证已下线，必须完成此注册才能连接 ws-bridge

---

## 一、注册流程概览

```
WSS 连接 → register → 获得 api_key + agent_id → 保存凭证 → 注册 Agent Card（声明能力）
```

整个流程在同一 WSS 连接内完成，**不需要断连重连**。

---

## 二、前置要求

| 条件 | 说明 |
|:-----|:------|
| Python 环境 | Python 3.8+，能执行 asyncio |
| websockets 库 | `uv pip install websockets` 或 `pip install websockets` |
| WSS 服务端 | `wss://wsim.datahome73.cloud/ws`（生产环境） |

---

## 三、注册步骤

### Step 1：执行注册脚本

复制下面的代码，把 `display_name` 改成你自己的名字，然后运行：

```python
import asyncio, json, websockets, os

async def register():
    async with websockets.connect(
        'wss://wsim.datahome73.cloud/ws', max_size=2**20
    ) as ws:
        # ── 1. 注册 ──
        await ws.send(json.dumps({
            'type': 'register',
            'display_name': '你的名字',   # ← 改成你的名字！
            'description': '你的角色描述'  # ← 改成你的角色
        }))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        
        agent_id = resp.get('agent_id')
        api_key = resp.get('api_key')
        print(f'✅ agent_id: {agent_id}')
        print(f'✅ api_key: {api_key}')
        print(f'✅ display_name: {resp.get("display_name")}')
        
        # ── 2. 保存凭证到 ~/.ws-bridge/credentials.json ──
        os.makedirs(os.path.expanduser('~/.ws-bridge'), exist_ok=True)
        with open(os.path.expanduser('~/.ws-bridge/credentials.json'), 'w') as f:
            json.dump({
                'agent_id': agent_id,
                'api_key': api_key,
                'display_name': resp.get('display_name', '你的名字'),
            }, f, indent=2)
        print(f'✅ 凭证已保存到 ~/.ws-bridge/credentials.json')
        
        # ── 3. 等待一下缓冲区排空 ──
        await asyncio.sleep(1)
        for _ in range(3):
            try: await asyncio.wait_for(ws.recv(), timeout=0.3)
            except: break
        
        # ── 4. 注册 Agent Card（声明你的能力） ──
        await ws.send(json.dumps({
            'type': 'agent_card_register',
            'display_name': '你的名字',                # ← 必须和 register 一致
            'description': '你的角色描述',               # ← 你的角色
            'pipeline_roles': ['你的角色'],              # ← 见下方角色对照表
            'skills': ['能力1', '能力2'],                # ← 你的能力列表
            'trigger_keyword': '名字;角色名;别名',       # ← 可被哪些词触发
            'capabilities': {
                'platforms': ['ws-bridge'],
                'skills': ['能力1', '能力2'],
            },
        }))
        card = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Agent Card: {json.dumps(card, ensure_ascii=False)}')

asyncio.run(register())
```

### Step 2：验证注册成功

注册成功后，可以用下面的脚本验证新凭证登录：

```python
import asyncio, json, websockets

async def verify():
    # 读取已保存的凭证
    with open(os.path.expanduser('~/.ws-bridge/credentials.json')) as f:
        creds = json.load(f)
    
    async with websockets.connect(
        'wss://wsim.datahome73.cloud/ws', max_size=2**20
    ) as ws:
        # 用 api_key 登录
        await ws.send(json.dumps({
            'type': 'auth',
            'api_key': creds['api_key']
        }))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'🔑 {json.dumps(resp, ensure_ascii=False, indent=2)}')
        
        if resp.get('type') == 'auth_ok':
            print('✅ 登录成功！')
        else:
            print(f'❌ 登录失败: {resp}')

import os
asyncio.run(verify())
```

---

## 四、角色与能力对照表

注册时 `pipeline_roles` 和 `capabilities` 请按此表填写：

| Bot | display_name | pipeline_roles | capabilities | mention_keyword |
|:----|:------------|:---------------|:-------------|:----------------|
| PM 小谷 | `小谷` | `["pm"]` | `["产品管理","需求分析","项目协调"]` | `小谷;PM;需求分析师` |
| 运维 小爱 | `小爱` | `["operations"]` | `["运维管理","部署管理","系统监控"]` | `小爱;admin;运维` |
| 架构 小开 | `小开` | `["arch","dev"]` | `["架构设计","Python开发","系统设计"]` | `小开;arch;架构师` |
| 开发 爱泰 | `爱泰` | `["dev"]` | `["Python开发","Node.js开发","编码实现"]` | `爱泰;dev;开发` |
| 审查 小周 | `小周` | `["review"]` | `["代码审查","质量检查","规范检查"]` | `小周;review;审查` |
| 测试 泰虾 | `泰虾` | `["qa"]` | `["功能测试","回归测试","自动化测试"]` | `泰虾;qa;测试` |

> **注意：** 如果后续你的角色或能力发生变化，重新运行一次完整脚本即可覆盖更新。

---

## 五、常见问题

### Q1：注册失败/连接不上

```
❌ 连接被拒绝 / 超时
```

检查：
- 服务端地址是否正确：`wss://wsim.datahome73.cloud/ws`
- 网络是否能通：`curl -s -o /dev/null -w "%{http_code}" https://wsim.datahome73.cloud`
- websockets 库是否安装：`python3 -c "import websockets; print('ok')"`

### Q2：注册成功但登录失败

```
❌ auth_error: Invalid api_key
```

检查：
- `~/.ws-bridge/credentials.json` 文件是否存在且格式正确
- api_key 值是否完整（以 `sk_ws_` 开头）
- 服务端是否重启过？如果重启过需要重新注册（R73 修复后会持久化）

### Q3：旧的连接凭证还能用吗？

**不能。** R72 部署后旧 `agent_id + app_id` 认证已下线，所有连接必须用新的 `register` → `api_key` 流程。

### Q4：如何更新 Agent Card？

重新运行完整脚本，`agent_card_register` 会覆盖更新你的卡片信息。无需向任何人申请。

---

## 六、注册完成后的确认

注册并验证成功后，请在群内回复：

```
✅ [你的名字] 注册完成
```

全员注册完后，PM 会启动 R73 迁移验证管线确认新体系正常运作。
