# R95 — Auto Pipeline 停止 & 断点续跑命令

> **版本：** v1.0 初稿
> **日期：** 2026-07-10
> **作者：** 大宏（项目负责人）
> **状态：** 📝 待评审

---

## 1. 背景

R88→R92 五轮迭代实现了 AutoRouter 全自动管线推进，R93 减法清理旧体系后，管线流程趋于稳定。但在实际使用中暴露了一个**核心操作缺失**：

> **启动 auto 的是我，但 auto 卡死后我停不下来、也调不了。**

### 当前痛点

```
!pipeline_start R94 → 创建了旧 config 的管线
  ↓
  Step 2 (arch) 卡死 ⛔️
  ↓
  没有 pipeline_stop 命令
  ↓
  不能 restart --from step4
  ↓
  只能干等或手动清理工作区（不可控）
```

| 问题 | 后果 |
|:-----|:------|
| 管线卡死后无法终止 | 工作区被占用，新管线不能启动 |
| 不能指定起始步骤重跑 | 必须从 Step 1 重来，浪费 bot 时间 |
| 无主动停止命令 | 只能等超时或人工干预清理数据 |

---

## 2. 目标

新增两条命令，让 auto pipeline **可停、可调**：

```
!pipeline_stop R<N>              # 停掉卡死的 auto 管线
!pipeline_start R<N> --from step<N>  # 从指定步骤重新开始
```

### 核心原则

1. **谁启动谁停止** — 发起者有权 stop 自己启动的管线
2. **断点续跑是继续，不是重来** — `--from step4` 表示跳过 step1-3，直接执行 step4+ 的 handler
3. **状态可查询** — stop 后 `!pipeline_status R<N>` 应显示 `stopped` 状态
4. **幂等安全** — 已完成的步骤不会因为 stop+restart 被重复执行

---

## 3. 功能详细描述

### 3.1 `!pipeline_stop R<N>`

| 属性 | 值 |
|:-----|:----|
| 命令 | `!pipeline_stop R<N>` |
| 权限 | 管线的发起者（谁发的 `!pipeline_start`）、admin 频道 |
| 行为 | 标记管线为 `stopped` → 取消当前 step 的超时等待 → 清理 AutoRouter 的任务队列 |
| 效果 | 工作区保留（数据不丢失），管线状态变 `stopped` |
| 响应 | `🛑 Pipeline R<N> 已停止` |

**注意点：**
- stop 后工作区**不删除**，保留现场供排查
- stop 不会影响其他正在运行的管线
- 重复 stop 同一管线 → 幂等，返回 `✅ Pipeline R<N> 已停止（无需操作）`

### 3.2 `!pipeline_start R<N> --from step<N>`

| 属性 | 值 |
|:-----|:----|
| 命令 | `!pipeline_start R<N> --from step<N>` |
| 参数 | `step<N>` 是 WORK_PLAN 中的步骤号（如 `step4`, `step2`） |
| 行为 | 跳过 `<stepN` 的所有步骤，从 `step<N>` 开始执行 |
| 前置条件 | 管线存在且状态为 `stopped` 或 `failed` |
| 响应 | `🚂 Pipeline R<N> 从 Step N 重新启动` |

**注意点：**
- `--from step1` = 等同于不带 `--from` 的正常启动
- `--from` 只能用在已停止/失败的管线上，不能中断正在运行的管线
- 如果指定的 step 编号 > WORK_PLAN 总步骤数 → 报错 `❌ step<N> 超出范围`
- 如果管线状态为 `running` → 报错 `❌ Pipeline R<N> 正在运行，请先 !pipeline_stop`

---

## 4. 状态变更流程

```
        new
         │
         ▼
    ┌─────────┐    !pipeline_start    ┌───────────┐
    │  idle   │ ──────────────────→   │  running  │
    └─────────┘                       └─────┬─────┘
                                            │
                              ┌──────────────┼──────────────┐
                              │              │              │
                              ▼              ▼              ▼
                        ┌─────────┐   ┌─────────┐   ┌─────────┐
                        │ success │   │ failed  │   │ stopped │
                        └─────────┘   └────┬────┘   └────┬────┘
                                           │              │
                                           └──────┬───────┘
                                                  │
                                                  ▼
                                        ┌──────────────────┐
                                        │ !pipeline_start  │
                                        │ --from step<N>   │  →  running
                                        └──────────────────┘
```

**新状态说明：**

| 状态 | 含义 | 可操作 |
|:-----|:-----|:-------|
| `stopped` | 用户主动停止 | 可 `--from step<N>` 重启，可 `!pipeline_stop` 再次确认（幂等） |
| `failed` | AutoRouter 检测到步骤超时/错误 | 可 `--from step<N>` 重启 |

---

## 5. 不受影响的已有功能

| 功能 | 说明 |
|:-----|:------|
| `!pipeline_start R<N>`（无 `--from`） | 行为不变，创建新管线 |
| `!pipeline_status R<N>` | 新增显示 `stopped` 状态 |
| `!list_workspaces` | 不受影响 |
| AutoRouter 自动推进 | 不受影响，stop 仅中断当前管线 |
| 多管线并发 | stop 只影响指定管线 |

---

## 6. 验收标准

### 6.1 `!pipeline_stop` 验证

- [ ] 对一个 running 管线执行 stop → 状态变 `stopped`
- [ ] 对 idle 管线执行 stop → 报错 `❌ Pipeline R<N> 不在运行状态`
- [ ] 对已 stopped 管线重复 stop → 幂等提示 `✅ 已停止（无需操作）`
- [ ] stop 后工作区保留，可用 `!list_workspaces` 看到
- [ ] stop 后其他管线不受影响
- [ ] 非发起者执行 stop → 权限拒绝 `❌ 只有发起者可以 stop 此管线`

### 6.2 `!pipeline_start --from` 验证

- [ ] 对 stopped 管线执行 `--from step4` → 从 step4 开始，跳过 step1-3
- [ ] 对 failed 管线执行 `--from step2` → 从 step2 开始
- [ ] 对 running 管线执行 `--from` → 报错 `❌ 请先 !pipeline_stop`
- [ ] `--from step1` = 等同于正常启动
- [ ] `--from step99`（超出范围）→ 报错 `❌ step99 超出范围`
- [ ] 跳过的步骤不被标记为 "已完成"（保持 `skipped` 或 `not_run`）
- [ ] 从 stepN 恢复后，AutoRouter 正常接管后续步骤

### 6.3 查询验证

- [ ] `!pipeline_status R<N>` 能正确显示 `stopped`
- [ ] stop 前的已完成步骤状态保留（不丢失）

---

## 7. 时间线

| 阶段 | 内容 | 预计耗时 |
|:----|:-----|:---------|
| 1 | 需求文档评审 | 1 天 |
| 2 | 架构设计方案 | 1-2 天 |
| 3 | 开发 | 2-3 天 |
| 4 | 测试 | 1 天 |
| 5 | 部署 | 完成 |

---

## 8. 评审问题

1. `!pipeline_stop` 的权限范围是否需要放宽到 workspace 管理员？还是保持仅发起者？
2. `--from step<N>` 跳过前置步骤后，`step<N>` 能否独立运作（不依赖前置输出的变量）？
3. 是否需要定时自动清理长期 `stopped` 的工作区（如超过 24 小时）？
