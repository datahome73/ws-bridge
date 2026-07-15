# R120 工作计划 — 自动派活管线全流程验证轮（文档版）

> **状态：** 📝 草稿（待需求审核通过）
> **auto_start:** false

---

## 概述

R120 是**文档验证轮**——每步产出一份轻量团队知识文档（≤ 10 句），不写一行代码。核心目的是反复验证自动派活管道的稳定性。

**关键原则：**
- 不碰代码、不新建 bot、不改配置
- 每步 ≤ 10 句，10 分钟内完成
- 遇到断点源码修复（不手动绕行）

---

## 执行步骤

### Step 1：PM 启动管线（小谷 📋）

**任务：** 需求文档审核通过 → 发 `##start##R120`

**产出：** `docs/R120/R120-product-requirements.md`（本文件）

**操作清单：**
```
1. 用户审核通过需求文档
2. 小谷发: ##start##R120
3. 系统自动确认 Step 1
4. 检查:
   - ✅ 系统回复
   - 🚀 小开收到 Step 2 派活
   - 📬 PM 收到通知
```

**检查点：**
- [ ] ① ✅ `##start##R120` 回复正常
- [ ] ② 🚀 小开收到 Step 2 派活
- [ ] ③ 📬 PM 收到通知

---

### Step 2：系统架构概述（小开 📐）

**任务：** 产出 `docs/R120/ARCH_OVERVIEW.md`

**内容：** ≤ 10 句，描述 ws-bridge 核心组件（Gateway / WS Server / Pipeline Manager / Web UI / Bot Client）

**操作清单：**
```
1. 收到 Step 2 派活消息
2. 产出 docs/R120/ARCH_OVERVIEW.md（≤ 10 句）
3. git add + commit + push dev
4. 向 _inbox:server 发送: 已完成 ✅ R120 Step 2
5. 检查:
   - ✅ 系统确认回复
   - 🚀 爱泰收到 Step 3 派活
   - 📬 PM 收到通知
```

**回复格式：** `已完成 ✅ R120 Step 2`

**检查点：**
- [ ] ① ✅ 系统确认回复
- [ ] ② 🚀 爱泰收到 Step 3 派活
- [ ] ③ 📬 PM 收到通知

---

### Step 3：开发环境与流程说明（爱泰 💻）

**任务：** 产出 `docs/R120/DEV_NOTES.md`

**内容：** ≤ 10 句，开发环境搭建 + 常用命令 + 分支策略 + 常见问题

**操作清单：**
```
1. 收到 Step 3 派活消息
2. 产出 docs/R120/DEV_NOTES.md（≤ 10 句）
3. git add + commit + push dev
4. 向 _inbox:server 发送: 已完成 ✅ R120 Step 3
5. 检查:
   - ✅ 系统确认回复
   - 🚀 小周收到 Step 4 派活
   - 📬 PM 收到通知
```

**回复格式：** `已完成 ✅ R120 Step 3`

**检查点：**
- [ ] ① ✅ 系统确认回复
- [ ] ② 🚀 小周收到 Step 4 派活
- [ ] ③ 📬 PM 收到通知

---

### Step 4：代码审查清单（小周 👁）

**任务：** 产出 `docs/R120/REVIEW_CHECKLIST.md`

**内容：** ≤ 10 句，阻塞/非阻塞项 + 审查流程 + 特殊关注点

**操作清单：**
```
1. 收到 Step 4 派活消息
2. 产出 docs/R120/REVIEW_CHECKLIST.md（≤ 10 句）
3. git add + commit + push dev
4. 向 _inbox:server 发送: 已完成 ✅ R120 Step 4
5. 检查:
   - ✅ 系统确认回复
   - 🚀 泰虾收到 Step 5 派活
   - 📬 PM 收到通知
```

**回复格式：** `已完成 ✅ R120 Step 4`

**检查点：**
- [ ] ① ✅ 系统确认回复
- [ ] ② 🚀 泰虾收到 Step 5 派活
- [ ] ③ 📬 PM 收到通知

---

### Step 5：QA 验证清单（泰虾 🦐）

**任务：** 产出 `docs/R120/QA_CHECKLIST.md`

**内容：** ≤ 10 句，测试类型 + 自动派活关键检查项 + 验证流程 + 报告模板

**操作清单：**
```
1. 收到 Step 5 派活消息
2. 产出 docs/R120/QA_CHECKLIST.md（≤ 10 句）
3. git add + commit + push dev
4. 向 _inbox:server 发送: 已完成 ✅ R120 Step 5
5. 检查:
   - ✅ 系统确认回复
   - 🚀 小爱收到 Step 6 派活
   - 📬 PM 收到通知
```

**回复格式：** `已完成 ✅ R120 Step 5`

**检查点：**
- [ ] ① ✅ 系统确认回复
- [ ] ② 🚀 小爱收到 Step 6 派活
- [ ] ③ 📬 PM 收到通知

---

### Step 6：运维操作手册 + 合并归档（小爱 🚢）

**任务：** 产出 `docs/R120/OPS_RUNBOOK.md` + 合并 dev → main

**内容：** ≤ 10 句，部署流程 + 环境变量 + 故障排查 + 常用命令

**操作清单：**
```
1. 收到 Step 6 派活消息
2. 产出 docs/R120/OPS_RUNBOOK.md（≤ 10 句）
3. git add + commit + push dev
4. git checkout main && git merge dev && git push origin main
5. 向 _inbox:server 发送: 已完成 ✅ R120 Step 6
6. 检查:
   - ✅ 系统确认回复
   - 📬 PM 收到全管线完成通知
   - 管线状态 COMPLETED
```

**回复格式：** `已完成 ✅ R120 Step 6`

**检查点：**
- [ ] ① ✅ 系统确认回复
- [ ] ② ✅ 管线 COMPLETED
- [ ] ③ 📬 PM 收到全管线完成通知

---

## 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|:----|:----:|:----:|:-----|
| Bot 接到派活后不知从何下手 | 低 | 中 | 派活消息附带需求 URL，每步有明确产出说明 |
| 自动派活断流 | 低 | 高 | 按 R119 已验证的方案走，遇到断点源码修复 |
| 容器重启打断管线 | 低 | 中 | 容器重启测试是可选加分项，不强制 |
| 文档写太长 | 中 | 低 | 严格控制 ≤ 10 句，超过的 bot 自行缩减 |

---

## 验证完成条件

- [ ] 前置：用户审核通过需求文档 ✅
- [ ] `##start##R120` → Step 2 自动派活 ✅
- [ ] Step 2 完成（ARCH_OVERVIEW.md）→ Step 3 自动派活 ✅
- [ ] Step 3 完成（DEV_NOTES.md）→ Step 4 自动派活 ✅
- [ ] Step 4 完成（REVIEW_CHECKLIST.md）→ Step 5 自动派活 ✅
- [ ] Step 5 完成（QA_CHECKLIST.md）→ Step 6 自动派活 ✅
- [ ] Step 6 完成（OPS_RUNBOOK.md + merge main）→ COMPLETED + PM 通知 ✅
- [ ] 所有断点已源码修复 ✅
- [ ] 6 份文档均 ≤ 10 句 ✅
