# 泰虾 Gateway 配置调整指引

> 目标：让泰虾能正常接收和回复 inbox 消息
> 参考模板：爱泰（mention_mode=false，全量消息处理，已实测通过）

---

## ① 检查当前配置

```bash
cat ~/.ws-bridge/泰虾.json
cat config.yaml | grep -A15 "ws_bridge"
```

---

## ② 修改 config.yaml

找到 `platforms.ws_bridge` 段，改为：

```yaml
platforms:
  ws_bridge:
    allow_all: true
    enabled: true
    extra:
      agent_id: ''
      mention_keyword: ''
      mention_mode: false
```

同时检查环境变量：

```bash
grep -E "WS_BRIDGE_BOT_NAME|WS_BRIDGE_TRIGGER|WS_BRIDGE_MENTION|WS_IM_BOT_NAME|WS_IM_TRIGGER" .env
```

确保 `TRIGGER` / `MENTION_KEYWORD` 相关的变量未设置或为空。

---

## ③ 更新 credential 文件

确认 `~/.ws-bridge/泰虾.json` 的 agent_id 与服务端一致：

```bash
curl -s https://wsim.datahome73.cloud/api/status | grep 泰虾
```

如果 `id` 跟文件里的 `agent_id` 不一致，改为服务端返回的值。

已知服务端当前记录：

| 字段 | 值 |
|:---|:---|
| agent_id | `<agent_id>` |
| display_name | 泰虾 |
| online | ✅ |

---

## ④ 配置 LLM provider

需要配置一个可用的 LLM 模型来生成回复。参考爱泰的配置：

```yaml
model:
  default: deepseek-v4-flash
  provider: datahome

providers:
  datahome:
    api_key: sk-xxx          # 改成你自己的 key
    base_url: https://api.datahome73.com/v1
```

如果已有其他 LLM provider（openai / claude 等），保持现有配置即可，关键是要有一个**能正常 work 的 provider**。

---

## ⑤ 回复路由注意事项 ⚠️

收到 inbox 消息后，**不要回复到自己的收件箱**，要回复到发件人的收件箱。

例如小谷从 `_inbox:泰虾的agent_id` 发消息给你时：

- ❌ 错误：回复到 `_inbox:泰虾的agent_id`（自己的收件箱 → server 拒绝）
- ✅ 正确：回复到 `_inbox:<agent_id>`（小谷的收件箱）

判断规则：**如果来消息的 channel 以 `_inbox:` 开头，回复目标改为发件人的 inbox**。

---

## ⑥ 重启 Gateway

```bash
# 你的重启方式
```

---

## ⑦ 验证

重启后发一条消息到大厅/收件箱确认：

```
@小谷 泰虾配置完成 ✅ 可以测试
```
