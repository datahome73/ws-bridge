# WORK_PLAN.md — R139

## 目标

将 main.py 的 `_sm_handle_*()` 规则回调（~190 行）+ 规则注册代码（~76 行）提取为独立模块 `scenario_rules.py`，main.py 精简至 ~470 行。附带修复 scenario_matcher.py L515 未定义变量 bug。

---

## Step 分派

| Step | 角色 | 责任人 | 具体工作 |
|:----:|:-----|:-------|:---------|
| **1** | 📋 需求 | 小谷 | 编写 `R139-product-requirements.md` + `WORK_PLAN.md` |
| **2** | 📐 技术方案 | 小开 (arch) | 评估创建 `scenario_rules.py` 的技术可行性 + 依赖关系 |
| **3** | 💻 编码 | 爱泰 (dev) | ① 创建 `scenario_rules.py`（逐字迁移 main.py L469-L735 的回调+注册）<br>② main.py 删除 L469-L735，追加 `from .scenario_rules import register_all_rules; register_all_rules()`<br>③ 修复 scenario_matcher.py L515 的 `_main` bug（改为 lazy import）<br>④ 更新 `server/ws_server/README.md`（模块清单 + §9 重构进度）|
| **4** | 👁️ 审查 | 小周 (review) | 审查 scenario_rules.py 与 main.py 原版逐字一致 |
| **5** | 🧪 QA | 泰虾 (QA) | 编译验证（C1-C4）+ 功能回归（T1-T13）|
| **6** | 🚢 部署 | 小爱 (ops) | 合 main + 部署 |

> 经理负责管线调度，不含在步骤表中。

---

## 改动预览

| 文件 | 操作 | 行数变化 | 说明 |
|:-----|:----|:---------|:------|
| `server/ws_server/scenario_rules.py` | 🆕 新增 | ~270 行 | 规则回调+注册，从 main.py 逐字迁移 |
| `server/ws_server/main.py` | ✂️ 删除 L469-L735 + 追加 2 行 | -266 + 2 = **-264 行** | 736 → ~472 |
| `server/ws_server/scenario_matcher.py` | 🔧 修复 L515 | +1 行 | `_main` → lazy import |
| `server/ws_server/README.md` | 📝 更新 | ~±5 行 | 模块清单 + §9 |

---

## 验收计数

- 编译验证：4 项（C1-C4）
- 功能回归：13 项（T1-T13）
- 代码审查：3 项（R1-R3）
- **合计：20 项**
