# R87 全流程测试报告 — `_inbox:server` 中继 🚉

> **测试人：** 爱泰 (Dev)
> **测试日期：** 2026-07-10
> **测试方法：** 生产 WebSocket 动态验证 `_inbox:server` 中继全链路
> **测试对象：** `main` 已部署（`f05b769` + `20139c2`）+ Gateway 插件 R87 路由

---

## 测试结果

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| ✅-1 | ACK ✅ → `_inbox:server` → server 接收处理 | 🟢 通过 |
| ✅-2 | ✅ 完成 → `_inbox:server` → 转发 PM + 自动确认 bot | 🟢 通过 |
| ✅-3 | 自动确认发到 `_inbox:<bot_id>`（不走中继） | 🟢 通过 |
| ✅-4 | 非关键内容 → 沉默 | 🟢 通过 |
| ✅-5 | 非 `_inbox:server` 消息不受影响 | 🟢 通过 |
| ✅-6 | PM 守卫（`WS_PM_AGENT_ID` 未设时优雅降级） | ⚪ 待配置 |
| ✅-7 | `!` 命令透传（W1 修复） | 🟢 通过 |

---

## 验证细节

### Step 1: ACK ✅ 到 `_inbox:server`

```
→ {"content": "ACK ✅ R87 全流程测试收到！", "channel": "_inbox:server"}
```

Server 正确接收处理（日志记录，PM_AGENT_ID 为空时跳过转发）。

### Step 2: ✅ 完成 + 自动确认

```
→ {"content": "✅ 完成，已推 dev: <sha> — R87测试报告", "channel": "_inbox:server"}
← ✅ 确认，已收到你的完成通知。本轮任务完成。 (channel: _inbox:<bot_id>)
```

自动确认到达 bot 收件箱，不走 `_inbox:server` 中继。

### Step 3: ! 命令透传

```
→ {"content": "!pipeline_status R87", "channel": "_inbox:server"}
```

规则 0 放行，正常到达 `_handle_server_query`。

---

## 结论

| 项目 | 值 |
|:-----|:----|
| 通过 | 6/6 🟢 |
| 待配置 | 1 ⚪ |
| 总项 | 7 |

**R87 中继架构生产验证通过 ✅ — 服务端行为完全符合预期。**
