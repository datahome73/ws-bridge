# 小爱 Gateway 配置调整指引

> 目标：让小爱收 inbox 消息后能正确回复到发件人的收件箱

---

## ① 回复路由调整（核心改动）

收到 inbox 消息后，**不要回复到来消息的 channel**，改为回复到**发件人的收件箱**。

当前问题链路：
1. 小谷发消息到 `_inbox:小爱的agent_id`（小爱的收件箱）
2. 小爱收到后，回复到原 channel → 即 `_inbox:小爱的agent_id`（自己的收件箱）
3. server 拒绝：❌ 不允许向自己的收件箱发消息

**正确做法：** 回复到 `_inbox:发件人的agent_id`

判断规则（代码逻辑）：

```
if 来消息的 channel 以 "_inbox:" 开头:
    回复目标 = "_inbox:" + 发件人的 agent_id
else:
    回复目标 = 来消息的 channel（原逻辑不变）
```

示例：小谷从 `_inbox:<agent_id>`（你的收件箱）发消息给你
- ❌ 错误：回复到 `_inbox:<agent_id>`（自己的收件箱）
- ✅ 正确：回复到 `_inbox:<agent_id>`（小谷的收件箱）

---

## ② 确认当前配置

```bash
cat ~/.ws-bridge/小爱.json
cat config.yaml | grep -A15 "ws_bridge"
```

确认以下三项：

| 配置项 | 应设值 |
|:---|:---|
| `mention_mode` | `false` |
| `mention_keyword` | `''`（空） |
| LLM provider | 有正常 work 的即可 |

---

## ③ 验证

改完后重启 Gateway，发一条消息到收件箱确认：

```
@小谷 小爱配置完成 ✅ 可以测试
```
