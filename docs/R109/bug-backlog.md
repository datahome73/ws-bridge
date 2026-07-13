# R109 Bug Backlog

> 发现于 R109 管线推进过程中，后续轮次逐步排查修复。

---

## L1 — 手动 inbox 透传

无已知 bug（已验证可靠）。

## L2 — Server 中转（`_inbox:server` + `to_agent`）

| # | Bug | 描述 | 文件位置 |
|:-:|:----|:-----|:---------|
| 1 | **ws_client ACK 不匹配** | `ws_client.py` 发消息时带 msg_id，等 server 回 ack 匹配。但 server 的 `_handle_server_relay` 直接 `return True` 不返回 ack，或返回的 `{"type":"ack"}` 不含 `id` 字段，client 无法匹配到 pending_acks，永远超时重试 | `clients/python/ws_client.py` 的 `_handle_message()` 匹配 `ack_id = msg.get("id")` ← server 没发 `id` |
| 2 | **PM 被 guard 拦截不能发 `_inbox:server`** | 小谷（PM）发消息到 `_inbox:server` 时，`_handle_server_relay` 在安全守卫处直接 `return True`，拒绝消息。PM 无法发送 `✅ 完成` 信号触发 `_try_advance_pipeline` | `server/main.py` L2605-2611 |
| 3 | **格式不一致：`✅ 完成` vs `已完成 ✅`** | Relay handler（L2629）接受 `已完成 ✅` 和 `✅ 完成` 两种前缀。但 `_try_advance_pipeline`（L2387）的正则只匹配 `已完成 ✅ R(\d+) Step (\d+)`，用 `✅ 完成` 前缀不会触发管线推进 | `server/main.py` L2387 & L2629 |
| 4 | **L2 bot 发消息后被断连** | 新注册 bot（L2）向 `_inbox:server` 发送消息后，服务器立即关闭连接（code 1000），不返回错误信息。连接无法复用以接收后续广播 | `server/main.py` handler 流程，具体原因待排查 |

## L3 — 全自动 Auto Dispatch

| # | Bug | 描述 | 文件位置 |
|:-:|:----|:-----|:---------|
| 5 | **auto dispatch 未触发推进** | pipeline_start 后 pipeline_contexts.json 标记了 `running`，但 Step 1→Step 2 的 auto dispatch 未实际派活给目标 bot。目标 bot inbox 收件箱为空 | `server/main.py` `_auto_dispatch()` L2468-2523 |

---

## 排查线索

- Bug 4（L2 断连）可能与 pipeline manager 初始化异常有关，`_ensure_pipeline_manager()` 或 `PipelineContextManager(data_dir=...)` 可能因文件权限/路径问题崩溃
- Bug 5（auto dispatch 未触发）可能是因为没有 bot 发送 `已完成 ✅` 信号，管道停留在 Step 1 未推进
- 所有 inbox 消息的 `save_message()` 缺失问题已在 R109 需求文档中记录，尚未修复
