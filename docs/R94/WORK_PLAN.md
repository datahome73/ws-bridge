# R94 — ws-bridge 新 Bot 入驻技能 WORK_PLAN

> **状态：** 📝 待审核
> **日期：** 2026-07-11
> **前置条件：** ✅ R94 需求文档已通过评审 (`cd0b4c0`)

---

## 一、范围

| 项 | 值 |
|:---|:----|
| 轮次 | R94 |
| 类型 | 📄 文档协作（非代码） |
| 目标 | 编写 `ws-bridge-registration` skill，打通新 bot 入驻全流程 |
| 需求文档 | `docs/R94/R94-product-requirements.md` |

## 二、拓扑（派活链）

```
R94 → 小开(arch) → 爱泰(dev) → 小周(review) → 泰虾(qa) → 小爱(ops) → 小谷(pm/汇总)
```

各 bot 在接收任务后 **24h 内**输出初稿到 `docs/R94/contrib/` 目录下，推 dev 分支。

## 三、任务分解

### Step 1 — 小开 (Arch)：Gateway 接入指南

**输出：** `docs/R94/contrib/gateway-config.md`
**推分支：** dev

内容：
- Hermes Gateway 插件配置模板（config.yaml + .env）
- WS_IM_URL / WS_IM_BOT_NAME / WS_IM_API_KEY 三选一方案
- `allow_all: true` + `mention_mode: false` 的配置说明
- 认证流程：auth → auth_ok → 进入 lobby
- 生产环境注意事项（日志、重连、systemd）
- ⚠️ 小爱补充：VPS 部署、凭证安全、重启恢复

### Step 2 — 爱泰 (Dev)：注册脚本

**输出：** `docs/R94/contrib/register.py`
**推分支：** dev

内容：
- 一站式脚本：WSS connect → register → 存凭证 → agent_card_register
- 字段验证（display_name、capabilities 为 dict、trigger_keyword 为顶层字符串）
- 凭证保存 `~/.ws-bridge/{name}.json`
- 脚本内带详细注释（无需外部说明段落就能跑）
- 参考模板：现有 `templates/bot-guide.md` 中的注册部分

### Step 3 — 小周 (Review)：Inbox 协议精简版

**输出：** `docs/R94/contrib/inbox-protocol.md`
**推分支：** dev

从现有 `docs/inbox-message-protocol.md` (461行) 中提取新 bot 最需要的核心内容：
- 收到消息的 JSON 结构（channel、from_agent、content）
- ACK ✅ / ✅ 完成 回复规则
- \_inbox:server 中继通道
- 4 步通信 SOP 图
- 回复格式规则（简洁版）
- 注意事项：不要回复 Step 4 确认

### Step 4 — 泰虾 (QA)：排错手册 + 验证清单

**输出：** `docs/R94/contrib/troubleshooting.md`
**推分支：** dev

内容：
- 常见错误：注册断开→Web 红误判、字段类型错误、频率限制、服务端重启 api_key 丢失
- 已验证的修复路径
- 验证清单（逐项 check）：
  - [ ] register 成功获得 api_key
  - [ ] agent_card_register 返回 status=online
  - [ ] auth 认证通过
  - [ ] \!agent_card get 显示 display_name 正确
  - [ ] @用户名 可达（其他 bot 可提及）
  - [ ] inbox 消息收得到、回得出

### Step 5 — 小爱 (Ops)：运维补充

**输出：** 在 `docs/R94/contrib/gateway-config.md` 中追加运维注释
**推分支：** dev

补充内容：
- 服务端是否已开放注册入口（确认 `register` 协议对所有 WSS 连接可用）
- 服务端重启后的凭证恢复流程
- 多 bot 环境下的凭证隔离（每个 bot 独立文件）
- 日志路径和查看方法
- 安全注意事项（api_key 泄露处理）

### Step 6 — 小谷 (PM)：汇总整合

**输入：** 以上 5 份初稿（从 dev 拉取 `docs/R94/contrib/`）
**输出：** 完整 `ws-bridge-registration` skill
**推分支：** dev

整合动作：
1. 用 `skill_manage(action='create')` 创建新 skill
2. 参考 meyo-community 的 SKILL.md 结构编排
3. 各 bot 初稿作为 `scripts/` 和 `references/` 放入 skill 目录
4. 主 SKILL.md 用 YAML frontmatter + markdown 体
5. 脱敏检查：确保无内部 bot 名残留
6. 通知全员 skill 已就绪

## 四、交付物

| # | 产出 | 负责人 | 位置 |
|:-:|:----|:-------|:-----|
| 1 | gateway-config.md | 小开 + 小爱 | `docs/R94/contrib/` → `skill/references/` |
| 2 | register.py | 爱泰 | `docs/R94/contrib/` → `skill/scripts/` |
| 3 | inbox-protocol.md | 小周 | `docs/R94/contrib/` → `skill/references/` |
| 4 | troubleshooting.md + verify.py | 泰虾 | `docs/R94/contrib/` → `skill/references/` |
| 5 | 完整 SKILL.md | 小谷 | `skills/software-development/ws-bridge-registration/SKILL.md` |

## 五、约束

1. **外部视角** — 所有产出物不能引用「小谷/小爱/小开」等内部名称，用 `{Bot显示名}` 占位
2. **可验证** — 每个步骤后附带验证方法
3. **推 dev** — 所有初稿推到 dev 分支的 `docs/R94/contrib/` 目录下
4. **24h** — 各 bot 接到任务后 24h 内输出
5. **脱敏** — 汇总前小谷做脱敏检查
