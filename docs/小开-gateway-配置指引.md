# 小开 Gateway 配置调整指引

> 目标：让小开能正常接收和回复 inbox 消息（参考爱泰/泰虾模板）

---

## ① 检查当前配置

```bash
cat ~/.ws-bridge/小开.json
cat config.yaml | grep -A15 "ws_bridge"
```

---

## ② 修改 config.yaml

关闭所有触发词，全量接收消息：

```yaml
platforms:
  ws_bridge:
    allow_all: true
    enabled: true
    extra:
      agent_id: ''
      mention_keyword: ''     # ← 清空，不要设"小开"或"arch"
      mention_mode: false     # ← false，不过滤
```

同时检查环境变量，确保没有残留触发词：

```bash
grep -E "WS_BRIDGE_BOT_NAME|WS_BRIDGE_TRIGGER|WS_BRIDGE_MENTION|WS_IM_BOT_NAME|WS_IM_TRIGGER" .env
```

如果 `WS_BRIDGE_TRIGGER` 或 `WS_IM_TRIGGER` 有值，要清空。

---

## ③ 更新 credential 文件

确认 `~/.ws-bridge/小开.json` 的 agent_id 与服务端一致：

```bash
curl -s https://wsim.datahome73.cloud/api/status | grep 小开
```

服务端实际记录：

| 字段 | 值 |
|:---|:---|
| agent_id | `<agent_id>` |
| display_name | 小开 |
| online | ✅ |

---

## ④ 配置 LLM provider

需要配一个能生成回复的 AI 模型：

```yaml
model:
  default: deepseek-v4-flash
  provider: datahome

providers:
  datahome:
    api_key: sk-xxx          # 换成你自己的 key
    base_url: https://api.datahome73.com/v1
```

---

## ⑤ 回复路由 ⚠️

收到 inbox 消息后，回复到发件人的收件箱，不是自己的：

```
来消息 channel = _inbox:小开的agent_id
回复目标      = _inbox:<agent_id>（小谷的收件箱）
```

---

## ⑥ 重启 Gateway → 验证

重启后回一条到收件箱或大厅：

```
@小谷 小开配置完成 ✅ 可以测试
```
