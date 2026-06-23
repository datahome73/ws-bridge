# R34 Dev 测试报告

> **日期：** 2026-06-23
> **测试环境：** `ws-im-dev.datahome73.com`
> **代码版本：** `r34-rehearsal` (commit `ae21675`)
> **测试者：** 🦐 泰虾

---

## 环境状态

| 检查项 | 结果 |
|:-------|:----:|
| HTTPS/health | ❌ **502 Bad Gateway** — WS Bridge 容器内进程未响应 |
| WebSocket | ❌ **502** — 反向代理无法转发到 WS Bridge |
| nginx 前端 | ✅ 运行中（1.24.0） |

**结论：** Dev 容器在部署后 WS Bridge 服务未正常启动。需要 🦸 小爱 排查容器状态（容器内 `docker ps` + `docker logs`）。

## 代码验证（替代测试）

由于 dev 环境不可用，以下验证通过 **代码审查 + AST 语法检查 + 逻辑推演** 完成。

### 需求 A — 工作室重置

| 用例 | 描述 | 预期 | 验证方式 | 结果 |
|:----:|:-----|:-----|:--------|:----:|
| A-T1 | 管理员对活跃工作室发 reset | 所有成员收到 `force: true` 广播 | 代码审查 + 离线入队逻辑推演 | ⏳ Dev 拯救后验证 |
| A-T2 | 管理员对 CLOSING 工作室发 reset | 返回 error | 代码审查：`ws_info.state == CLOSING` 分支 | ✅ 代码通过 |
| A-T3 | 非管理员发 workspace_reset | 权限不足 error | 代码审查：`_users.get(agent_id, {}).get("role") != "admin"` 守卫 | ✅ 代码通过 |
| A-T4 | 不存在的工作室发 reset | "工作室不存在" error | 代码审查：`ws_mod.get_workspace()` 空值检查 | ✅ 代码通过 |
| A-T5 | 管理员 reset 含离线成员工作室 | 离线成员入队 + `_flush_offline_push` 定时器启动 | 代码审查：离线 push 逻辑 + 定时器启动 | ✅ 代码通过（审查建议已落实） |
| A-T6 | R29 兼容：`all: true` | 重置所有成员到 lobby | 代码审查：`elif all_flag:` 分支保留 | ✅ 代码通过 |
| A-T7 | R29 兼容：`target` | 重置单个成员到 lobby | 代码审查：`elif target_id:` 分支保留 | ✅ 代码通过 |
| A-T8 | workspace_reset ACK 含 delivery | `{total, sent, offline, targets, offline_targets}` | 代码审查：ACK 行 #1252-1262 | ✅ 代码通过 |

### 需求 B — 消息状态透传

| 用例 | 描述 | 预期 | 验证方式 | 结果 |
|:----:|:-----|:-----|:--------|:----:|
| B-T1 | 消息到有成员在线的工作室 | ACK `delivery.sent >= 1` | 代码审查：工作区路径 #390-409 | ✅ 代码通过 |
| B-T2 | 消息到有成员在线+离线的工作室 | ACK `delivery.{sent, offline}` | 代码审查：离线计算逻辑 | ✅ 代码通过 |
| B-T3 | 限速时发消息 | 收到 `rate_limited` error | 代码审查：`_check_rate_limit` 守卫不变 | ✅ 代码通过 |
| B-T4 | 无前缀消息发大厅 | 收到 error | 代码审查：`_classify_lobby_message('plain')` 守卫 | ✅ 代码通过 |
| B-T5 | 📢 广播 ACK 含 delivery 字段 | `delivery.{total, sent, offline, targets, offline_targets}` | 代码审查：走廊区 ACK #585-604 | ✅ 代码通过 |
| B-T6 | 向后兼容：旧 `MSG_DELIVERY_STATUS` | 保留不删除 | 代码审查：2 处 admin-only 保留 | ✅ 代码通过 |
| B-T7 | ACK delivery.total = sent + offline | 一致性校验 | 代码审查：total=len(非发送者), sent=在线, offline=total-sent | ✅ 代码通过 |

## 代码改动摘要

| 文件 | 行 | 核心改动 |
|:----|:--:|:--------|
| `server/handler.py` | +141/-11 | workspace_reset workspace_id 分支 + 双路径 ACK delivery |
| `server/__main__.py` | +88/-0 | 双入口同步 + import 补充 |

**语法验证：** ✅ 两文件 AST 解析通过

## 阻塞项

- **🔴 Dev 容器 502** — WS Bridge 服务未启动。需要 🦸 小爱 登录 VPS 排查：
  ```bash
  # 1. 检查容器
  docker ps | grep ws-bridge
  # 2. 查看日志
  docker logs <container_id> --tail 50
  # 3. 如果需要重启
  docker restart <container_id>
  ```
  修复后通知 🦐 泰虾跑完整测试脚本。

## 测试脚本

测试脚本已就绪，覆盖 7 项可行测试（A-T2~A-T8 + B-T3~B-T7）：
- `docs/R34/r34-test-script.py`

等待 Dev 容器修复后执行 `python3 docs/R34/r34-test-script.py`。
