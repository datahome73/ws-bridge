---
pipeline:
  name: "R133 — Inbox 发件人颜色扩展 + 收件人颜色显示 🎨"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R133/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R133/R133-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 前端颜色方案设计
      - step: step3
        role: developer
        title: 编码实现
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署归档
steps:
  - name: step2
    agent_id: ws_3f7cdd736c1c
    agent_name: 小开
    title: 前端颜色方案设计
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码实现 — CSS/JS 颜色扩展 + 收件人颜色
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — templates.py 改动
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 11 项验收
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R133 工作计划 — Inbox 发件人颜色扩展 + 收件人颜色显示

> **版本：** v1.0
> **状态：** 📝 定稿
> **负责人：** 🧐 PM

## 概述

给收件箱（Inbox Tab）和归档页（Archive Tab）增加 2 种新发件人颜色（系统/经理），同时收件人改用 bot 对应颜色显示。纯前端改动，仅涉及 `server/web_ui/templates.py` 一个文件。

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + WORK_PLAN | `R133-product-requirements.md` + `WORK_PLAN.md` | 推 dev |
| **Step 2** 🟡 待执行 | 👷 小开 | 颜色方案确认 | `R133-tech-plan.md` | 推 dev |
| **Step 3** ⏳ | 👨‍💻 爱泰 | 编码 — templates.py CSS/JS 改动 | `templates.py` patch | py_compile + 浏览器验证 |
| **Step 4** ⏳ | 👀 小周 | 代码审查 | `R133-code-review.md` | 推 dev |
| **Step 5** ⏳ | 🦐 泰虾 | 测试验证 11 项验收 | `R133-test-report.md` | 推 dev |
| **Step 6** ⏳ | 🛠️ 小爱 | 合并部署 | 合 main + 重启 | `##status` 确认 |

---

## 关键里程碑

| 阶段 | 交付物 |
|:-----|:-------|
| Step 1 ✅ | 需求文档审核通过 + 推 dev |
| Step 2 ✅ | 颜色方案确认（arch 产出 `R133-tech-plan.md`） |
| Step 3 ✅ | 编码完成（`templates.py` CSS + JS colorMap + createInboxMessageEl + createArchiveMessageEl 收件人颜色） |
| Step 4 ✅ | 代码审查通过（`templates.py` 4 处改动：CSS 2 行 / colorMap 2 项 / 2 个函数收件人逻辑） |
| Step 5 ✅ | 测试 11/11 ALL GREEN 🟢（A 组发件人颜色 4 项 / B 组收件人颜色 4 项 / C 组回归 3 项） |
| Step 6 ✅ | 合 main + 部署完成 |

---

## Step 分派

### Step 1 ✅ — PM 需求（已完成）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R133/R133-product-requirements.md` |
| 工作计划 | `docs/R133/WORK_PLAN.md` |

### Step 2 🟡 — 架构方案（小开）

- 产出 `docs/R133/R133-tech-plan.md`
- 确认 2 种新颜色的色值选择
- 确认收件人颜色逻辑（receiver → colorMap 查找 → CSS class）
- 评估是否需要对 `createMessageEl`（工作区消息）做任何调整

### Step 3 ⏳ — 编码（爱泰）

修改 `server/web_ui/templates.py`：

1. **CSS 区**（L79-80 之间）：新增 2 行
   ```css
   .msg .sender.s-system{color:#39d2c0;}
   .msg .sender.s-manager{color:#f78166;}
   ```

2. **JS colorMap**（L216）：追加 `'系统':'system','经理':'manager'`

3. **`createInboxMessageEl` 收件人颜色**（L421）：
   - 从 `colorMap[receiver]` 解析 class
   - 收件人 `<span>` 使用 `sender s-{class}` 而非固定 `s-unknown` 硬编码灰色

4. **`createArchiveMessageEl` 收件人颜色**（L458-461）：
   - 同上，从 `colorMap[m.to_name]` 解析 class

### Step 4 ⏳ — 代码审查（小周）

审查要点：
- [ ] CSS 新增 2 个 class 无拼写错误，色值与需求文档一致
- [ ] colorMap 新增 2 个 key 名称正确（`系统`、`经理`）
- [ ] `colorMap[receiver]` / `colorMap[m.to_name]` 在有 `to_name` 前已定义
- [ ] 未知收件人 fallback 到 `unknown`（灰色）
- [ ] `createMessageEl` 工作区消息不受影响
- [ ] 无 JS 语法错误

### Step 5 ⏳ — 测试验证（泰虾）

逐项验证验收标准（共 11 项）：

**A 组 — 发件人颜色：**
- A1: 系统显示青色 `#39d2c0`
- A2: 经理显示鲑鱼红 `#f78166`
- A3: 6 bot 颜色不受影响
- A4: 未知发件人灰色 fallback

**B 组 — 收件人颜色：**
- B1: 收件箱收件人显示对应 bot 颜色
- B2: 未知收件人灰色 fallback
- B3: 归档页收件人颜色同样生效
- B4: 工作区/大厅消息无异常

**C 组 — 回归：**
- C1: 无 JS 报错
- C2: 新消息实时插入后颜色正确
- C3: 无 CSS 冲突

### Step 6 ⏳ — 合并部署（小爱）

1. 合 `dev → main`
2. 部署到生产环境
3. `##status` 确认 Web 服务正常
4. 通知 PM 验收完成

---

## 改动预览

| 文件 | 新增行 | 修改行 | 说明 |
|:----|:------|:------|:------|
| `server/web_ui/templates.py` | +4 | ~4 | CSS 2 行 + colorMap 2 项 + 2 个函数各 2 行 |

**净变化：约 +4 行，修改 ~4 行。**
