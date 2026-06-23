# R33 开发计划

> **仓库：** `datahome73/ws-bridge`（公开仓库，MIT）
> **工作流：** v5.2（前置决策 + 自动化管线）
> **范围：** 三项 Bug A/B/C 修复（Web端体验修复）
> **状态：** ✅ 管線中

---

## 🔶 前置决策区（已完成）

### Step A — 需求文档 ✅
- 📄 `docs/R33/R33-product-requirements.md`（v0.2）
- 🧑 项目负责人：✅ 审核通过

### Step B — 工作计划 ✅
- 📄 `docs/R33/WORK_PLAN.md`
- 🧑 项目负责人：✅ 审核通过

---

## 🟢 自动化管线

| Step | 环节 | 角色 | 状态 | 产出 |
|:----:|:-----|:----:|:----:|:-----|
| 1 | 建工作室 | 🦸 小爱 | ✅ | R33 开发工作室 |
| 2 | 点名报道 | 🦐 泰虾 | ✅ | 全员就位 |
| 3 | 技术方案 | 🏗️ 小开 | ✅ | `docs/R33/tech-plan.md` |
| 4 | 编码实现 | 💻 爱泰 | ✅ | commit `d9c1b09` |
| 5 | 代码审查 | 🔍 小周 | ✅ | 审查通过 |
| 6 | Dev 部署 | 🦸 小爱 | ✅ | `ws-im-dev.datahome73.com` |
| **7** | **Dev 测试** | **🦐 泰虾** | **✅** | **`docs/R33/test-report.md`** |
| **8** | **合并部署&归档** | **🦸 小爱** | **⏳** | **→ main + 关工作室** |

### Step 7 — Dev 测试（泰虾 🦐）✅
- 测试日期：2026-06-23
- 测试环境：`ws-im-dev.datahome73.com`
- 测试报告：`docs/R33/test-report.md`（commit `c85ef83`）
- 结论：**11/11 全量通过 ✅**

### Step 8 — 合并部署 & 归档（小爱 🦸）⏳
| 子步骤 | 动作 | 产出 |
|:------:|:-----|:-----|
| 8a | 根据测试报告结论，合并 `r33-rehearsal` → `dev` → `main` | main 分支更新 |
| 8b | 部署正式容器 + 关闭工作室 + 归档文档 | 轮次闭环 |

---

## 需求范围

三项 Bug（仅 Web 端）：

| Bug | 根因 | 改法 | 文件 |
|:---:|:-----|:-----|:----:|
| A — Tab 刷新丢失 | TAB_STATE 纯内存无持久化 | localStorage 双重保险 | `server/templates.py` |
| B — 部署登出 | session 文件丢失无自愈 | 前端 401/WS 降级处理 | `server/templates.py` + `web_viewer.py` |
| C — 历史群错乱 | 数据卷不一致 | 前端空结果区分 | `server/templates.py` |

改动量：+55 / -7 行，净增 +48 行，仅改 `templates.py` + `web_viewer.py`。
