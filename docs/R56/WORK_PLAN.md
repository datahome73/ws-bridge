# R56 工作计划 — 自动驾驶管线通信层修复 + 过渡期协调流程

> **版本：** v0.1 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-29

---

## 🔴 过渡期行为规则（全体必读 — 提醒一起执行）

> R56 是过渡修复轮，目标是从「人工拼凑」进化到「高可靠半自动」。以下规则本轮必须遵守。

### 规则 1：PM 主动监控不是可选项

| Step 推进后 | PM 必须做的事 |
|:------------|:-------------|
| `!step_complete` 执行后 30 秒 | 检查 `!pipeline_status` Step 指针是否前移 |
| Step 指针前移后 1 分钟 | 检查工作室中目标 bot 是否回复确认 |
| Step 指针前移后 5 分钟 | 目标 bot 无响应 → 准备升级 code block |
| 连续 2 步需项目负责人激活 | 暂停管线并报告「通信链路可能断裂」 |

### 规则 2：升级 code block 格式统一

```
@接收人 StepN — 任务描述
- 需求文档：{URL}
- 技术方案：{URL}
- 期望产出：{具体要求}
- 完成后 !step_complete stepN --output <sha>
```

### 规则 3：完成就必须推进

| 谁 | 做什么 |
|:---|:-------|
| 编码者 | 推 dev 后立即在工作室内 `!step_complete step3 --output <sha>` |
| 方案师 | 推方案后立即 `!step_complete step2 --output <sha>` |
| 审查者 | 审查通过后立即 `!step_complete step4 --output <sha>` |
| PM | 任何产出推 git 后、即使不是自己做的，也可 `!step_complete` 推进 |

### 规则 4：先不丢，再求静

`_send_to_agent` 的定向通知如果目标 bot 不在线，**必须回退到工作室全广播**，不能静默丢。可靠性优先于减少回声。

### 规则 5：不抢占活跃 Step（同 R55 规则 5）

### 规则 6：Step 交接不回声（同 R55 规则 6）

---

## 管线步骤

```
R56 三方向工作流：

┌─────────────────────────────────────────────────────┐
│  🔶 方向 A  修复 _send_to_agent 通知丢失（~5行）     │
│  🔶 方向 B  生产环境通信链路诊断（报告）              │
│  🔶 方向 C  过渡期协调流程设计（报告）                │
└─────────────────────────────────────────────────────┘
                            │
                            ▼
           ┌───────────────────────────────┐
           │ Step 1 !pipeline_start R56    │
           │ Step 2 技术方案（A+B+C）        │
           │ Step 3 编码（A）+ 诊断（B）并行  │
           │ Step 4 代码审查（A）+ 报告审查   │
           │ Step 5 测试验证（A+B+C）        │
           │ Step 6 合并部署 + 归档          │
           └───────────────────────────────┘
```

---

## 🔴 Git 操作规范（全员遵守）

> 以下规范是 R56 实操中确认的必要纪律，避免代码冲突和版本混乱。

### 原则 1：改前先拉取（Pull Before Edit）

每次编辑本地文件前，先拉取远程最新代码：

```bash
git pull --ff-only origin dev
```

| 时机 | 操作 |
|:-----|:------|
| 开始编辑任何文件前 | `git pull --ff-only origin dev` |
| 多人并行开发时，每次 commit 前 | `git pull --rebase origin dev` |

> **为什么：** 避免本地 stale 版本覆盖远程最新改动，减少冲突。

### 原则 2：只提交改动文件（Commit Only Changes）

不执行 `git add .` 或 `git add -A` 等批量添加命令。**只手动添加本次实际改动的文件：**

```bash
# ✅ 正确 — 只 add 改动的具体文件
git add docs/R56/WORK_PLAN.md
git add docs/R56/R56-product-requirements.md

# ❌ 错误 — 可能带入无关改动
git add .
git add -A
git add docs/          # 整个目录
```

| 场景 | 操作 |
|:-----|:------|
| 改了一个文档 | `git add docs/R56/WORK_PLAN.md` |
| 改了代码 + 文档 | 分别 add 两个文件 |
| 改了 3 个文件 | 逐个 add（可以一次 `git add file1 file2 file3`） |

> **为什么：** 本地工作目录可能包含未完成的实验性改动、临时调试代码、或其他角色的遗留改动。批量 add 会将无关改动带入 commit，导致代码库污染和冲突。

### 原则 3：开发在 dev，合并归管理员（Dev Branch Only）

| 操作 | 责任人 | 说明 |
|:-----|:-------|:------|
| 代码开发 | 💻 各角色 | 所有 commit 推 `origin/dev` |
| 文档编写 | 🧐 PM / 🏗️ 架构师 | 所有文档推 `origin/dev` |
| 代码审查 | 🔍 审查者 | 审查 dev 分支代码 |
| 测试验证 | 🦐 测试者 | 在 dev 容器上测试 |
| 合并 dev → main | 🦸 超级管理员（admin-bot） | **仅超级管理员有 main 权限** |
| 正式部署 | 🦸 超级管理员（admin-bot） | 合并后部署正式容器 |

**禁止：** 非管理员直接推 main 分支。

> **为什么：** main 是正式发布分支，需要经过完整测试验证和审查后才能合并。各角色在 dev 上完成各自环节后，由超级管理员统一合并部署。

### 原则 4：远程 URL 安全（Token Not Leaked）

每次通过 HTTPS 推送后，**立即恢复远程 URL** 为干净的公开 URL：

```bash
# 推送前：设置带 token 的 URL
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/datahome73/ws-bridge.git"

# 推送
git push origin dev

# 推送后：立即恢复干净 URL
git remote set-url origin https://github.com/datahome73/ws-bridge.git
```

> **为什么：** token 嵌入 URL 后，`git remote -v` 会暴露完整 token。恢复干净 URL 避免 token 泄露到日志或他人查看。

### 原则 5：commit 信息格式统一

```
<type>(<scope>): <简短描述>

# 类型：
# docs   — 文档改动（需求/WORK_PLAN/报告）
# feat   — 新功能
# fix    — Bug 修复
# chore  — 杂项（TODO更新/归档）

# 示例：
# docs(R56): v0.1 产品需求 — 通信层修复 + 过渡期流程
# fix(R56): _send_to_agent 失败回退到工作室广播
# docs(R56): Step 5 ✅ 测试报告 — 11/11 验收通过
```

---

### 角色对照表

| 角色 | Step 2 | Step 3 | Step 4 | Step 5 | Step 6 |
|:----|:------:|:------:|:------:|:------:|:------:|
| 🏗️ 架构师 | 🟢 技术方案 | — | — | — | — |
| 💻 编码者 | — | 🟢 编码（A） | — | — | — |
| 🧐 PM | — | 🟢 诊断（B）+ 流程（C） | — | — | — |
| 🔍 审查者 | — | — | 🟢 审查 | — | — |
| 🦐 测试者 | — | — | — | 🟢 测试 | — |
| 🦸 超级管理员（admin-bot） | — | — | — | — | 🟢 合并部署 + 归档 |

---

### Step 1：管线启动 🧐 PM

```bash
!pipeline_start R56 --from step2 --mode auto
```

- 默认 `--mode auto`（自动驾驶模式）
- 管线启动后各角色自动切到 `ws:R56-dev`
- PM 立即 `!pipeline_status` 验证部署是否生效

### Step 2：技术方案 🏗️ 架构师

**产出：** `docs/R56/R56-tech-plan.md`

覆盖三个方向：

| 方向 | 内容 | 备注 |
|:----:|:-----|:-----|
| **A** | `_send_to_agent` 失败回退方案 | A-a: 定向+回退广播双保险，~5 行 |
| **B** | 通信链路 7 段诊断方案 | 诊断方法、执行方式、输出格式 |
| **C** | 过渡期 PM 操作 SOP | PM 监控流程、升级条件、code block 模板 |

**完成后：** `!step_complete step2 --output <sha>`

### Step 3：编码 + 诊断并行

#### 3-A 编码 💻 编码者（方向 A）

**改动点：** `server/handler.py` — `_send_to_agent()` 函数

**目标行为：**
```python
# 当前（R55）：定向发送失败 → return False（静默丢）
# 修复后：定向发送失败 → write_chat_log(workspace_channel) + 全广播通知
conns = _connections.get(agent_id, set())
if not conns:
    # R56: 回退到工作室广播 + write_chat_log
    _broadcast(ws_id, ...)
    write_chat_log(workspace_channel, ...)
    return True
```

**Commit 格式：** `fix(R56): _send_to_agent 失败回退到工作室广播`

**完成后：** `!step_complete step3 --output <sha>`

#### 3-B 通信链路诊断 🧐 PM（方向 B）

**产出：** `docs/R56/R56-comm-diagnosis.md`

诊断 7 段通信链路：

| # | 链路 | 预期方法 | 责任人 |
|:-:|:-----|:---------|:------|
| ① | `!pipeline_start` → 建工作室 | 直连 WS 触发 | PM |
| ② | 建工作室 → MSG_SET_ACTIVE_CHANNEL 发送 | 检查 handler 日志 + 工作室广播 | 架构师 |
| ③ | MSG_SET_ACTIVE_CHANNEL → bot 实际切换 | 各 bot 回复确认 | PM |
| ④ | 点名通知 → 各 bot 回复 | 工作室观察 | PM |
| ⑤ | `!step_complete` → `_send_to_agent` 送达 | 直连 WS 发命令，检视目标bot响应 | 测试者 |
| ⑥ | 定向失败 → 回退广播 | 断线目标 bot 后验证 | 测试者 |
| ⑦ | 下一角色实际接管工作 | 完整管线跑一轮 | 全员 |

**每段标注：** ✅ 正常 / ❌ 断裂 / ❓ 未确认，附 WS 直连原始响应原文

**完成后：** `!step_complete step3 --output <sha>`（注：诊断报告作为 Step 3 产出，PM 调 `!step_complete`）

#### 3-C 过渡期协调流程设计 🧐 PM（方向 C）

**产出：** 合并入 Step 5 验收或者单独 `docs/R56/R56-transition-process.md`

设计内容：
1. PM 监控检视 SOP（何时检查、检查什么、超时阈值）
2. 升级 code block 格式（模板 + 实际使用示例）
3. 项目负责人介入触发条件（连续 2 步需激活 → 暂停管线）

**完成后：** 随方向 B 诊断报告一起 `!step_complete step3 --output <sha>`

### Step 4：代码审查 🔍 审查者

**审查对象：**

| 方向 | 审查内容 | 重点 |
|:----:|:---------|:-----|
| A | `_send_to_agent` 回退逻辑 | ① 回退时是否写 chat_log ② 回退广播是否触发回声 ③ 在线 bot 是否仍走定向 |
| B | 诊断报告 | 诊断方法是否可靠、断裂点根因分析是否有代码级证据 |
| C | 过渡期流程 | SOP 是否可执行、模板是否完整 |

**审查重点（方向 A）：**

```python
# 关键检查点
1. _send_to_agent 失败后回退路径完整
2. 回退时 _broadcast 传入正确的 ws_id（不是 None）
3. write_chat_log 写入正确的频道名（工作室频道，不是 admin）
4. 回退后不产生新的回声循环（定向发送的日志在 admin，不回退 broadcast 的 admin 日志）
```

**完成后：** `!step_complete step4 --output <sha>`

### Step 5：测试验证 🦐 测试者

**基线：** Step 3 commit + 诊断报告 + 流程文档

#### 方向 A 验收（4 项）

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| A-1 | 目标 bot 在线时，`!step_complete` 交接通知定向送达，其他 bot 不收到 | 实测 Step 交接 |
| A-2 | 目标 bot 离线时，通知回退到工作室频道广播，不静默丢失 | 断线目标 bot 再调 `!step_complete` |
| A-3 | 离线 bot 重新上线后，能在工作室频道历史中读到通知 | 重连后检查工作室消息 |
| A-4 | `_admin` 频道保留完整 Step 交接日志 | 检查 admin 日志 |

#### 方向 B 验收（3 项）

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| B-1 | 7 个通信节点逐段标注了 ✅/❌/❓ | 诊断报告存在且完整 |
| B-2 | 每个 ❌ 节点附根因分析和修复建议 | 报告中逐项说明 |
| B-3 | 诊断通过真实 WS 直连生产执行 | 报告中附验证方法 |

#### 方向 C 验收（4 项）

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| C-1 | PM 能在 Step 完成后 1 分钟内确认下一角色状态 | 实操验证 |
| C-2 | Step 在 5 分钟内无响应 → PM 自动准备升级 code block | 模拟超时场景 |
| C-3 | 一轮管线全部 6 步能在合理时间内推进 | 完整跑一轮 |
| C-4 | 项目负责人 TG 激活次数从「每步必发」降到「偶尔兜底」 | 统计 |

#### 部署验证

| # | 验证项 | 说明 |
|:-:|:-------|:-----|
| D-1 | dev 容器部署后 `!pipeline_status` 返回有效数据 | 确认新代码已上线 |
| D-2 | `_send_to_agent` 回退逻辑在生产环境工作 | 断线+重连测试 |
| D-3 | 方向 C 流程在一轮管线中完整执行 | 实操跑一轮 |

**产出：** `docs/R56/R56-test-report.md`

**完成后：** `!step_complete step5 --output <sha>`

### Step 6：合并部署 + 归档 🦸 超级管理员（admin-bot）

> **执行者：** 🦸 超级管理员 — 唯一有 main 分支写入权限和生产容器操作权限的角色。
> **触发条件：** Step 5 测试验证通过后，PM 调 `!step_complete step5`，管线自动点名 admin-bot。

#### 6-1 合并前验证（Pre-Merge Check）

在合并 dev→main 之前，admin-bot 必须先验证以下条件全部满足：

| # | 检查项 | 通过条件 |
|:-:|:-------|:---------|
| V-1 | 测试报告完整 | `docs/R56/R56-test-report.md` 存在，11/11 验收通过 |
| V-2 | 代码审查通过 | `!step_complete step4` 已完成（`!pipeline_status` 确认） |
| V-3 | dev 分支最新 | `git fetch origin dev && git log origin/main..origin/dev --oneline` 列出本轮所有改动 commit |
| V-4 | 无未合并的冲突 | `git merge-tree $(git merge-base origin/main origin/dev) origin/main origin/dev` 无冲突输出 |
| V-5 | 无敏感信息泄露 | 对新增代码运行脱敏扫描（grep 内部名） |

> 如果 V-1~V-5 任一项不通过 → **暂停合并**，在工作室内通知 PM 跟进修复。不跳过检查强行合并。

#### 6-2 执行合并

```bash
# 1. 拉取最新的 dev 和 main
git fetch origin dev main

# 2. 切到本地 main，拉取最新
git checkout main
git pull --ff-only origin main

# 3. 合并 dev → main（--no-ff 保留分支历史）
git merge origin/dev --no-ff --no-edit

# 4. 推 main（仅 admin-bot 可执行）
git push origin main

# 5. 切回 dev 继续开发
git checkout dev
```

**合并后立即验证：**

```bash
# 确认 main 已有最新 commit
git log --oneline -3 origin/main

# 确认需要的内容已包含
git diff --stat origin/main..origin/dev  # 期望输出为空（dev 已合并到 main）
```

> **注意：** 仅合并本轮改动的 commit，不含未审核的 dev 改动。如果 dev 上有其他轮次的未完成代码，需要 cherry-pick 或协商范围。

#### 6-3 生产容器部署

合并完成后，admin-bot 执行生产容器部署：

| 步骤 | 操作 | 说明 |
|:-----|:------|:------|
| ① | 远程登录生产 VPS | SSH 或 docker context 连接 |
| ② | 拉取 main 最新代码 | `git pull origin main` |
| ③ | 重建并启动生产容器 | `docker compose build && docker compose up -d` |
| ④ | 检查容器健康状态 | `docker ps` 确认容器运行中 |
| ⑤ | 检查服务端启动日志 | `docker logs --tail 20 <container>` 确认无 ERROR |
| ⑥ | 验证 WebSocket 服务可连接 | `curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/health` 期望 200 |
| ⑦ | 验证 `!pipeline_status` 可用 | 直连生产 WS 或通过工作群发出，确认返回有效数据 |

**滚动更新策略：** 如果生产容器有多个副本，逐个替换（先停一个→启动新版本→验证→再停下一个）。避免全量重启导致服务中断。

#### 6-4 部署后验证（Post-Deploy Smoke Test）

部署上线后，admin-bot 执行快速冒烟测试：

```bash
# 检查方向 A 修复是否生效
!pipeline_status           # 确认返回管线状态表格，非错误
!step_complete step2       # 确认命令可执行（测试权限放开）
```

| # | 验证项 | 说明 |
|:-:|:-------|:-----|
| D-1 | 新容器 WebSocket 握手正常 | 直连生产 ws://... 收到 auth 响应 |
| D-2 | `!pipeline_status` 返回有效数据 | 确认新代码已上线 |
| D-3 | `_send_to_agent` 回退逻辑工作 | 断线目标 bot + 调 `!step_complete` → 工作室可见广播 |
| D-4 | Web 端可正常加载 | 浏览器打开 Web 聊天室确认 |

#### 6-5 归档

部署验证通过后，执行归档操作：

| 步骤 | 操作 | 责任人 |
|:-----|:------|:-------|
| ① | 更新 `docs/TODO.md` — 将 R56 完成项标记为 🟢 已完成 | 🧐 PM |
| ② | 关闭工作室 `ws:R56-dev` | 🦸 admin-bot |
| ③ | 恢复大厅接收（如已暂停） | 🦸 admin-bot（自动） |
| ④ | 通知 PM 管线完成 → PM 回复项目负责人 | 🦸 admin-bot → 🧐 PM |
| ⑤ | `!step_complete step6` 结束管线 | 🦸 admin-bot |

#### 6-6 回滚预案

如果部署后发现严重问题（P0/P1），admin-bot 执行回滚：

```bash
# 回滚 main 到上一版本
git revert HEAD --no-edit
git push origin main

# 重新部署旧版本容器
docker compose down
docker compose up -d

# 验证恢复
docker ps
docker logs --tail 10 <container>
```

**回滚后：** 立即在工作室内通知 PM 和项目负责人，说明回滚原因和计划修复的轮次。

---

**完成后：** `!step_complete step6` 结束管线 🎉

---

## 自动驾驶模式行为速查表

| 角色 | 传统模式行为 | 过渡期自动驾驶行为 |
|:----|:-----------|:----------------|
| 🏗️ 架构师 | 出方案 → 等人通知推进 | 出方案 → 推 git → `!step_complete step2` |
| 💻 编码者 | 编代码 → 等人通知推进 | 编代码 → 推 dev → `!step_complete step3` |
| 🔍 审查者 | 审代码 → 等人通知推进 | 审代码 → 推报告 → `!step_complete step4` |
| 🦐 测试者 | 测功能 → 等人通知推进 | 测功能 → 推报告 → `!step_complete step5` |
| 🧐 PM | 写需求 → 等架构师联系 | 写需求 → 推 dev → `!step_complete` + 主动检视超时 + 准备升级 |

---

## 关键约束

1. **方向 A 改动量极小（~5 行），但要审查充分** — 通信层改动影响面广，回退逻辑必须逐行验证
2. **方向 B 诊断必须通过真实 WS 直连生产，不模拟不本地** — 通信链路问题只在生产环境才能暴露
3. **方向 C 流程在 R56 管线执行中就应用** — 不用等流程写完再用，本轮管线 PM 直接按新流程操作
4. **修复优先于新功能** — 如果方向 B 诊断发现新问题，优先在本轮修复再报，不移入 TODO.md 等"下一轮"
