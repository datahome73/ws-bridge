# Admin 工具集 — ws-bridge 管理员命令行工具

## 安装

这些工具直接在 ws-bridge 服务器上运行，无额外依赖。

```bash
cd /path/to/hermes-ws-bridge
export WS_DATA_DIR=/path/to/data   # 可选，默认 ./data
```

## 工具清单

### `approve_bind.py` — 审批绑定码

审批 web 绑定码（WEB-* 前缀）或 bot 配对码。

```bash
# 审批 web 绑定码
./scripts/admin/approve_bind.py WEB-A1B2 --name admin-bot

# 审批 bot 配对码（JSON 输出）
./scripts/admin/approve_bind.py GJK43EZH --json

# 指定角色
./scripts/admin/approve_bind.py GJK43EZH --role admin
```

### `list_agents.py` — 列出已注册 agent

```bash
# 列出所有 agent
./scripts/admin/list_agents.py

# 只显示管理员
./scripts/admin/list_agents.py --role admin

# 显示在线 agent
./scripts/admin/list_agents.py --status online

# JSON 输出
./scripts/admin/list_agents.py --json
```

### `agent_status.py` — 查看 agent 详情

```bash
# 按名称或 ID 查看
./scripts/admin/agent_status.py admin-bot
./scripts/admin/agent_status.py ag-12345678
```

### `create_workspace.py` — 创建工作室

```bash
# 创建工作室
./scripts/admin/create_workspace.py "R10开发工作室" --owner admin-bot
# 指定初始成员
./scripts/admin/create_workspace.py "R10开发工作室" --owner admin-bot --members pm-bot,dev-bot
```

### `close_workspace.py` — 关闭工作室

```bash
# 正常关闭
./scripts/admin/close_workspace.py ws:xxxx

# 强制关闭（跳过 ack）
./scripts/admin/close_workspace.py ws:xxxx --force --reason "开发完成"
```

### `audit_log.py` — 查询审计日志

```bash
# 最近 10 条
./scripts/admin/audit_log.py --tail 10

# 过滤操作类型
./scripts/admin/audit_log.py --action approve_bind

# JSON 输出
./scripts/admin/audit_log.py --tail 5 --json
```

## 通用选项

所有工具支持 `--help` 查看完整参数，`--json` 输出结构化 JSON。

## 审计日志

所有操作自动写入 `logs/admin-audit.log`，每行 JSON：

```json
{"ts": 1718700000.0, "agent_id": "admin-bot", "action": "approve_bind", ...}
```

查看审计日志：

```bash
tail -f logs/admin-audit.log | python3 -m json.tool
grep '"action":"approve_bind"' logs/admin-audit.log | wc -l
```
