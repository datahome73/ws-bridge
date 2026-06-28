# R49 测试报告

| 项目 | 内容 |
|:-----|:-----|
| **轮次** | R49 |
| **定位** | 功能轮 — 方向A !命令全频道路由 + 方向B Agent Card 持久化 + 方向C 超时告警闭环 |
| **测试日期** | 2026-06-28 |
| **测试环境** | dev 容器 (ws-bridge-r42:dev, commit cc2ac5c) |
| **测试人员** | 测试工程师 (泰虾) |
| **测试方式** | 源码分析 + 单元验收 (39 项) + 集成冒烟 |

---

## 测试结果总览

| 方向 | 测试项 | 通过 | 失败 |
|:----|:------:|:---:|:---:|
| **方向 A** — `!` 命令全频道路由 | 9 | 9 ✅ | 0 |
| **方向 B** — Agent Card 持久化 | 17 | 17 ✅ | 0 |
| **方向 C** — 超时告警闭环 | 8 | 8 ✅ | 0 |
| **补充** — R48 代码共存验证 | 5 | 5 ✅ | 0 |
| **合计** | **39** | **39** ✅ | **0** |

---

## 方向 A：`!` 命令全频道路由

### 改动范围
`server/handler.py` — `handle_broadcast` 函数入口级通用路由

### 核心逻辑
```
handle_broadcast 入口：
  if content.startswith("!"):
      → _parse_command → _check_command_permission
      → cmd.handler → result → _send_cmd_response(source_channel)
      → return（不再落入 _admin 分支的旧 ! 处理）
  
  如果 ! 命令走完通用路由后，_admin 频道的后续代码只处理非 ! 消息
```

### 验收项

| ID | 测试项 | 结果 | 说明 |
|:---|:-------|:---:|:-----|
| A-1.1 | 通用 `!` 路由入口存在 | ✅ | `content.startswith("!")` 在 `handle_broadcast` 中 |
| A-1.2 | `!` 检测在 `_admin` 分支之前 | ✅ | 路由在频道判断之前拦截 |
| A-1.3 | `_send_cmd_response` 函数存在 | ✅ | 新增的响应发送函数 |
| A-2.1 | `_send_cmd_response` 发到来源频道 | ✅ | `channel` 参数透传 |
| A-2.2 | `_send_cmd_response` 持久化 | ✅ | `save_message` + `write_chat_log` |
| A-3.1 | `_admin` 频道非 `!` 回复可用命令 | ✅ | `ℹ️ 管理频道仅支持 ! 命令` |
| A-4.1 | 权限校验路径存在 | ✅ | `_check_command_permission` 调用 |
| A-4.2 | 权限不足回复 | ✅ | `❌` 前缀错误消息 |
| A-5.1 | 仅拦截 `!` 开头的消息 | ✅ | `startswith("!")` 精确匹配 |

### 要点
- **支持频道**: 所有频道（`_admin`、工作室、大厅等）
- **结果路由**: 命令执行结果发回来源频道，不固定写 `_admin`
- **权限控制**: 仍然经过 `_ADMIN_COMMANDS` 的 `min_role` 校验
- **向后兼容**: `_admin` 频道的 `!` 命令同样通过新路由，行为不变

---

## 方向 B：Agent Card 持久化

### 改动范围
`server/handler.py` — 新增 6 个函数 + 6 个命令注册

### 核心函数

| 函数 | 功能 |
|:-----|:-----|
| `_load_agent_cards()` | 从 `data/agent_cards.json` 加载卡片 |
| `_save_agent_cards(cards)` | 持久化写入磁盘 |
| `_get_agent_card_roles(agent_id, cards)` | 获取某人的管线角色列表 |
| `_find_agents_by_role(role, member_ids, cards)` | 按角色过滤工作区成员 |
| `_cmd_agent_card_*` | 6 个命令处理函数 (list/get/set/unset/reload) |

### 验收项

| ID | 测试项 | 结果 | 说明 |
|:---|:-------|:---:|:-----|
| B-1.1 | `pipeline_start` 引用 `_load_agent_cards` | ✅ | 管线启动时读取卡片 |
| B-1.2 | 有卡片时优先使用 | ✅ | `if cards:` 分支选取 |
| B-2.1 | 无卡片 fallback `auth.get_users()` | ✅ | 旧逻辑兼容 |
| B-3.1 | `step_complete` 引用 `_load_agent_cards` | ✅ | 点名时读取卡片 |
| B-3.2 | `step_complete` 用 `_find_agents_by_role` | ✅ | 按角色匹配成员 |
| B-4.1~6 | 6 个命令全部注册，min_role=3 | ✅ | 权限验证通过 |
| B-5.1 | `!agent_card <sub>` 子命令分发 | ✅ | 支持 list/get/set/unset/reload |
| B-5.2 | 子命令完整 | ✅ | 全部 4 个子命令存在 |
| B-7.1 | 路径在 `data/` 目录 | ✅ | 不进 git 跟踪 |
| B-8.1~3 | 核心函数存在 | ✅ | 全部可调用 |

### Agent Card 命令

```
!agent_card                      → 列出所有卡片
!agent_card list                 → 列出所有卡片
!agent_card get <agent_id>       → 查看单个卡片
!agent_card set <agent_id> --role <r1,r2> [--name <n>] [--skills <s1,s2>]  → 设置/更新
!agent_card unset <agent_id>     → 删除卡片
!agent_card reload               → 从磁盘重载（无需重启）
```

### 卡片格式（`data/agent_cards.json`）
```json
{
  "version": 1,
  "cards": {
    "agent_id_xxx": {
      "display_name": "小谷",
      "pipeline_roles": ["架构师", "需求分析师"],
      "skills": ["Python", "系统设计"],
      "status": "online",
      "updated_at": 1719561600.0
    }
  }
}
```

---

## 方向 C：超时告警闭环

### 改动范围
`server/handler.py` — `_send_watchdog_alert` + `_watchdog_rerollcall` + `_restore_pipeline_timers`

### 验收项

| ID | 测试项 | 结果 | 说明 |
|:---|:-------|:---:|:-----|
| C-1.1 | 超时告警发到工作室 | ✅ | `ws_id` 获取 + `conn.send_str` 发送 |
| C-1.2 | 超时消息含 `Timeout` | ✅ | 工作室收到 `⏰` 提醒 |
| C-2.1 | `_restore_pipeline_timers` 存在 | ✅ | 重启后恢复 |
| C-2.2 | 从 task store 恢复 | ✅ | `list_tasks_by_context` 读取 |
| C-2.3 | 恢复 `_set_pipeline_state` | ✅ | 恢复内存状态 |
| C-2.4 | `handle_broadcast` 入口调用 | ✅ | 首次消息时自动恢复 |
| C-3.1 | `timeout_hours` 可配置 | ✅ | `PIPELINE_STEP_MAP` 中 |
| C-4.1 | `_watchdog_rerollcall` 存在 | ✅ | 超时后自动重新点名 |

### 时序
```
1. Step 点名 → 注册超时计时器（timeout_hours）
2. 超时触发 → watchdog alert → _admin + 工作室双通道通知
3. 持续未响应 → rerollcall 自动重新点名
4. 服务器重启 → handle_broadcast 入口 _restore_pipeline_timers 恢复计时
```

---

## 补充：R48 代码共存验证

由于 git 合流关系，R49 dev 分支保留了 R48 的代码（方向 A 的 R48 回退在 main 分支）。以下验证确认这些代码与 R49 新功能兼容：

| ID | 测试项 | 结果 | 说明 |
|:---|:-------|:---:|:-----|
| S-1 | `step_complete` min_role=1 | ✅ | R48 保留，!路由正常工作 |
| S-2 | `work_plan_url` 保留 | ✅ | 与 R49 !路由不冲突 |
| S-3 | `PIPELINE_COMPLETE` 保留 | ✅ | _admin 通知持续有效 |
| S-4 | `close_workspace` 已更新 | ✅ | R49 改为 `close_workspace` |
| S-5 | default step=step2 | ✅ | R44 默认值保留 |

---

## 集成冒烟

| 检查项 | 结果 |
|:-------|:---:|
| dev 容器运行 | ✅ ws-bridge-r42:dev (commit cc2ac5c) |
| `/api/health` | ✅ `{"status": "ok"}` |
| 容器日志 | ✅ 无异常错误 |

---

## 结论

**R49 三项改动全部验收通过。**

| 方向 | 状态 | 备注 |
|:----|:----:|:-----|
| ✅ A — `!` 命令全频道路由 | 9/9 | 任何频道都可执行 `!` 命令 |
| ✅ B — Agent Card 持久化 | 17/17 | 6 个命令 + 文件持久化 |
| ✅ C — 超时告警闭环 | 8/8 | 工作室通知 + 重启恢复 + rerollcall |
| **合计** | **39/39** | **全部通过** 🎉 |
