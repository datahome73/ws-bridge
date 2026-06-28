# R49 开发计划

> **版本：** v0.1 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **编制人：** 🧐 PM
> **日期：** 2026-06-28
> **基于需求：** [R49-product-requirements.md v0.2 ✅](./R49-product-requirements.md)

---

## 一、轮次概览

| 维度 | 内容 |
|:----|:------|
| **轮次** | R49 |
| **需求文档** | 🔗 [R49-product-requirements.md v0.2 ✅](./R49-product-requirements.md) |
| **本轮改动范围** | 仅第①类（服务器代码 `server/handler.py` + 容器持久化配置） |
| **改动类型** | 基础设施修复（三个子方向，无代码冲突可平行开发） |

---

## 二、方向分解 & 验收对照

### 方向 A — `!` 命令全频道路由

将 `!` 命令解析从 `_admin` 频道独占改为全频道通用路由，工作室可直接执行 `!step_complete` 等管线命令。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| A-1 | 重构 `handle_broadcast`：将 `!` 前缀检测从 `_admin` 分支提到函数入口级通用路由 | `server/handler.py` | ~15 行 |
| A-2 | 非 `_admin` 频道执行 `!` 命令时，结果发回来源频道（工作室发回工作室） | `server/handler.py` | ~10 行 |
| A-3 | `_admin` 频道 `!` 命令行为零变化（向后兼容验证） | `server/handler.py` | ~5 行 |
| A-4 | 全频道 `!` 路由的权限校验不变（仍经过 `_check_command_permission`） | `server/handler.py` | 不新增 |
| A-5 | 非 `!` 前缀消息在所有频道中零行为变化 | `server/handler.py` | 不新增 |

**参考位置：** `handler.py` ≈行 1608-1649（当前 `_admin` 分支）+ 1650+（工作频道广播分支）

**验收标准覆盖：** A-1 ~ A-8

---

### 方向 B — 服务端角色映射持久化

在容器持久化层维护 `role_mapping.json`，`!pipeline_start` 和 `!step_complete` 从此文件读取角色匹配关系。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| B-1 | 新增 `_load_role_mapping()` 和 `_save_role_mapping()` 函数，读写 `data/role_mapping.json` | `server/handler.py` | ~20 行 |
| B-2 | `!pipeline_start` 创建工作室时：从 `role_mapping.json` 读取映射表→收集所有角色 agent→加入工作区 | `server/handler.py` | ~15 行 |
| B-3 | `!step_complete` 点名时：从映射表查工作区中 role 匹配的 agent→点名 | `server/handler.py` | ~10 行 |
| B-4 | 新增 `!role_map list / set / unset / reload` 四个 admin 命令，注册到 `_ADMIN_COMMANDS` | `server/handler.py` | ~30 行 |
| B-5 | 映射表为空/不存在时→完全回退到现有 `auth.get_users()` 按 role 匹配（向后兼容） | `server/handler.py` | ~5 行 |
| B-6 | 将 `role_mapping.json` 加入 `.gitignore`（不进 git 跟踪） | `.gitignore` | 1 行 |
| B-7 | 角色映射表初始配置脚本或容器卷挂载文档 | `docs/R49/` | — |

**验收标准覆盖：** B-1 ~ B-9

---

### 方向 C — 超时检测修复 + TG 协调链路

排查修复已有超时代码，确保超时计时器正确注册+触发+通知工作室。超时后工作室活跃 bot 直接 TG 私聊项目负责人协调。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| C-1 | 排查现有超时代码（查找 `_schedule_timeout` / `call_later` / 超时相关常量和回调），确认根因 | `server/handler.py` | 排查 |
| C-2 | 修复超时计时器注册：Step 点名时注册 N 分钟超时（N 可配置，default 60） | `server/handler.py` | ~15 行 |
| C-3 | 超时回调：向工作室发 ⏰ 催办消息 + 点名当前 Step 执行者 | `server/handler.py` | ~10 行 |
| C-4 | 服务端重启后恢复活跃管线的超时计时器（从 `_PIPELINE_STATE` 的 `started_at` 计算剩余时间） | `server/handler.py` | ~15 行 |
| C-5 | 超时时间配置项加到 `config.py`（`PIPELINE_TIMEOUT_MINUTES`，默认 60） | `server/config.py` | ~3 行 |

> **方向 C 的「TG 协调」环节无代码改动：** 超时后工作室 bot 主动 TG 私聊项目负责人是人工行为，非自动化。服务端只管超时通知发到工作室，升级链路靠人。

**验收标准覆盖：** C-1 ~ C-7

---

## 三、角色分工

| 角色 | 人员 | 职责 | 方向 |
|:----|:----|:-----|:----:|
| 🏗️ 架构师 | arch-bot | 技术方案编写 + 工作室讨论定稿 | 全部 |
| 💻 开发工程师 | dev-bot | 方向 A 编码（通用路由） + 方向 B 编码（映射表） + 方向 C 编码（超时修复） | A/B/C |
| 🔍 审查工程师 | review-bot | 代码审查 | 全部 |
| 🦐 测试工程师 | qa-bot | dev 容器部署 + 执行验收测试 | 全部 |
| 🧐 PM | pm-bot | 需求文档 + WORK_PLAN + 讨论主持 + 进度跟踪 | 全部 |
| 🦸 管理员 | admin-bot | 合并 dev→main 部署生产 + 角色映射表初始配置 | 全部 |

---

## 四、管线步骤

### 🔶 前置决策区

| Step | 名称 | 状态 | 负责人 | 产出 |
|:----:|:-----|:----:|:------|:-----|
| A | 需求文档 | ✅ **已审核** | 🧐 PM | `R49-product-requirements.md` v0.2 ✅ |
| B | 🆕 工作计划 | ✅ **已审核** | 🧐 PM | `WORK_PLAN.md` v0.1 ✅ |

> 前置决策区全部 ✅ 通过后，PM 在 `_admin` 频道触发 `!pipeline_start R49 --from step2` 进入自动化管线。

### 🟢 自动化管线（6 步）

| Step | 名称 | 状态 | 负责人 | 产出 | 验收 |
|:----:|:-----|:----:|:------|:-----|:----:|
| 1 | 🆕 管线启动 | ⏳ | 🦸 admin-bot → `!pipeline_start R49 --from step2` | 工作室 R49-dev 已就绪 | — |
| 2 | 🏗️ 技术方案 | ⏳ | 🏗️ arch-bot | `R49-tech-plan.md` | 工作室讨论定稿 |
| 3 | 💻 编码实现 | ✅ 已完成（6f40e43） | 💻 爱泰 | 方向 A ✅大宏, B+C ✅爱泰, 全推 dev | A:大宏/a6fef0f B+C:爱泰/6f40e43 |
| 4 | 🔍 代码审查 | ⏳ | 🔍 review-bot | `R49-code-review.md` | 逐方向验收覆盖 |
| 5 | 🦐 测试验证 | ⏳ | 🦐 qa-bot | dev 部署 + 全量验收 | 17 项验收 |
| 6 | 🦸 合并部署 | ⏳ | 🦸 admin-bot | 合并 dev→main + 角色映射表初始配置 | 部署后验证 |

### 方向 C 特殊性说明

方向 C（超时检测修复）的验收标准 C-1 ~ C-7 需要在管线实际运行中验证——即 R49 管线本身作为验证对象。这是鸡生蛋问题：要用修复后的超时机制来验证超时机制本身。处理方式：

- Step 5 测试时，通过手动模拟超时场景（设置极短超时时间如 2 分钟，然后不执行 `!step_complete` 等待超时触发）来验证 C-1 ~ C-4
- C-5（服务端重启后恢复计时器）和生产环境的超时时间调优在 Step 6 部署后验证

---

## 五、验收清单

| 方向 | 验收项 | 优先级 | 测试方法 |
|:----:|:------|:-----:|:---------|
| A | A-1: 工作室 `!step_complete` 执行成功 | 🔴 P0 | Step 5 手动验证 |
| A | A-2: 工作室 `!pipeline_status` 返回表格 | 🔴 P0 | Step 5 手动验证 |
| A | A-3: 工作室 `!pipeline_start` 创建工作室 | 🔴 P0 | Step 5 手动验证 |
| A | A-4: 结果发回来源频道 | 🔴 P0 | Step 5 验证 |
| A | A-5: `_admin` 频道向后兼容 | 🔴 P0 | Step 5 验证 |
| A | A-6: 非 `!` 消息行为不变 | 🔴 P0 | Step 5 验证 |
| A | A-7: 权限校验仍有效 | 🔴 P0 | Step 5 验证 |
| A | A-8: 端到端完整跑一轮 | 🟡 P1 | Step 5 验证 |
| B | B-1: `!pipeline_start` 从映射表读成员 | 🔴 P0 | Step 5 验证 |
| B | B-2: 映射文件不存在时回退 | 🔴 P0 | Step 5 验证 |
| B | B-3: `!step_complete` 从映射表点名 | 🔴 P0 | Step 5 验证 |
| B | B-4: `!role_map list` | 🟡 P1 | Step 5 验证 |
| B | B-5/B-6: `!role_map set/unset` | 🟡 P1 | Step 5 验证 |
| B | B-7: `!role_map reload` | 🟡 P1 | Step 5 验证 |
| B | B-8: 权限校验 | 🟡 P1 | Step 5 验证 |
| B | B-9: 不进 git | 🟡 P1 | Step 5 验证 |
| C | C-1/C-2: 超时计时器注册+触发 | 🔴 P0 | Step 5 模拟验证 |
| C | C-3: 超时催办发到工作室 | 🟡 P1 | Step 5 验证 |
| C | C-4: 重启后恢复计时 | 🟡 P1 | Step 6 部署后 |
| C | C-5: 配置可调 | 🟡 P1 | Step 5 验证 |
| C | C-6/C-7: 不跳过+可配置 | 🟢 P2 | Step 5 验证 |

**总数：** 22 项验收

---

## 六、关键约束

1. **⚠️ 角色映射表不进 git 跟踪** — `role_mapping.json` 文件放在容器持久化数据卷（如 `data/role_mapping.json`），不在 `docs/`、`server/` 等任何 git 跟踪目录下。`.gitignore` 中显式忽略该路径
2. **⚠️ 向后兼容** — 方向 A 的 `_admin` 频道 `!` 命令行为零变化；方向 B 的映射表为空时回退到现有 `auth.get_users()` 行为
3. **⚠️ `!role_map` 命令权限** — `min_role` 设为 3（工作室管理员/全局管理员），不开放给普通成员
4. **⚠️ 超时只通知不跳过** — 方向 C 的超时检测只能发通知，不能自动推进管线状态
5. **🟢 三方向可平行开发** — 方向 A（通用路由）、方向 B（持久化配置）、方向 C（超时修复）在 `handler.py` 中影响不同的函数段，无代码冲突，可 parallel 编码
6. **🟢 开发中不部署** — 三个方向全部完成并推 dev 后统一部署生产容器