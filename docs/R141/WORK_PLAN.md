# R141 代码清理轮 — 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** 📝 草稿

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求调研 → 出需求文档 |
| 🏗️ 架构师 | 小开 | 技术方案设计 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🦸 运维 | 小爱 | 部署 + 合并 main |

---

## 开发步骤

### Step 1 — 需求文档 🧐 小谷 ✅（已完成）

产出：`docs/R141/R141-product-requirements.md` + `docs/R141/WORK_PLAN.md`

已排查 main 分支的代码清理点，分 A/B/C 三类：

| 类别 | 内容 | 风险 |
|:----:|:-----|:----:|
| 🟢 A 类 | 8 处未使用导入/函数/死代码 | 安全删除，无行为变化 |
| 🟡 B 类 | workspace 死代码块(~77行) + state.py 重复定义 | 需确认无外部引用 |
| 🔴 C 类 | `_ROLE_AGENT_MAP` / `_step_ack_states` DEPRECATED 变量迁移 | 迁移到 PipelineContextManager |

---

### Step 2 — 技术方案 🏗️ 小开

产出：`docs/R141/R141-tech-plan.md`

评估 B 类（workspace 死代码）是否有隐蔽依赖，以及 C 类迁移的技术方案。

---

### Step 3 — 编码 💻 爱泰

按方案实现，建议分三次提交：

| 提交 | 内容 | 涉及文件 |
|:----:|:-----|:---------|
| 1/3 | A 类安全清理 | `main.py` ×4, `__main__.py` ×2, `scenario_matcher.py` ×1, `message_store.py` ×1 |
| 2/3 | B 类清理 | `main.py` L472~L548 删除, `state.py` L13 删除 |
| 3/3 | C 类迁移 | `state.py`, `agent_card.py`, `main.py`, `commands/pipeline.py`, `ack_machine.py`, `pipeline_engine.py` |

---

### Step 4 — 代码审查 🔍 小周

产出：`docs/R141/R141-code-review.md`

逐 commit 审查，重点：
- B-1 删除后 `ws_mod` 是否还有合法引用
- C-1 `_ROLE_AGENT_MAP` 多写路径是否全部迁移干净
- C-2 `_step_ack_states` 多读路径是否全部迁移干净

---

### Step 5 — Dev 测试 🦐 泰虾

产出：`docs/R141/R141-test-report.md`

验证 24/24 ALL GREEN。

---

### Step 6 — 合并 main + 部署 🦸 小爱

---

## 注意事项

1. `docs/R*/` 被 `.gitignore` 忽略，需 `git add -f` 强制提交
2. C 类迁移需确认所有读写路径都已迁移，不可遗漏
3. 安全优先——A 类+B 类先清理（无行为变化），C 类单独验证
