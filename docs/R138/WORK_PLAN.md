---
pipeline:
  name: "R138 — 引擎合并轮：engine2.py 吞并 pipeline_engine.py 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R138/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R138/R138-product-requirements.md"
  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 合并方案设计 — engine2→pipeline_engine 精确范围
      - step: step3
        role: developer
        title: 编码 — 替换 pipeline_engine.py + 删除 engine2.py + 更新 import
      - step: step4
        role: reviewer
        title: 代码审查 — import 正确性 + B-5 已修复
      - step: step5
        role: qa
        title: 测试验证 — 10 项验收
      - step: step6
        role: operations
        title: 合并部署归档
steps:
  - name: step2
    agent_id: ws_3f7cdd736c1c
    agent_name: 小开
    title: 技术方案 — PipelineEngine class 集成方案 + import 变更清单
    role: architect
    status: pending
  - name: step3
    agent_id: ws_0bb747d3ea2a
    agent_name: 爱泰
    title: 编码 — 替换 pipeline_engine.py + 删除 engine2.py + main/scenario_matcher/__main__ import 更新
    role: developer
    status: pending
  - name: step4
    agent_id: ws_fcf496ca1b4f
    agent_name: 小周
    title: 代码审查 — 无 engine2 残留 + B-5 修复确认 + 外部接口不变
    role: reviewer
    status: pending
  - name: step5
    agent_id: ws_eab784ac7652
    agent_name: 泰虾
    title: 测试验证 — 10 项验收标准（P0 级 8 项 + P1 级 2 项）
    role: qa
    status: pending
  - name: step6
    agent_id: ws_c47032fa1f67
    agent_name: 小爱
    title: 合 main 部署
    role: operations
    status: pending
---

# R138 工作计划 — 引擎合并轮

> **版本：** v1.0
> **状态：** ⬜ 待审核
> **日期：** 2026-07-20

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求文档 + 排查记录 |
| 🏗️ 架构师 | 小开 | 合并方案设计 → 编码审查 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🚢 Operations | 小爱 | 步骤 6 合 main 部署 |

---

## 合并总览

| MERGE# | 操作 | 涉及文件 | 行数 |
|:------:|:-----|:---------|:----:|
| MERGE-A | 替换 pipeline_engine.py 为 engine2 代码主体 | `pipeline_engine.py` | 1,544 替换 1,319 |
| MERGE-B | 吸收旧版有用功能（format_context/后台扫描等） | `pipeline_engine.py` | +50~100 |
| MERGE-C | B-5 自动修复（用 engine2 的 auto_dispatch） | `pipeline_engine.py` | 自动完成 |
| MERGE-D | 删除 engine2.py | `engine2.py` | -1,544 |
| IMPORT | 更新 import 路径 | `main.py`, `scenario_matcher.py`, `__main__.py` | ~10 行改动 |

---

## 合并顺序

1. **MERGE-A** — 将 engine2.py 的全部代码复制到 pipeline_engine.py
2. **MERGE-B** — 将旧 pipeline_engine.py 的 class 功能和后台扫描代码并入
3. **MERGE-C** — 确认 auto_dispatch 用的是 engine2 版本（无 PM fallback）
4. **MERGE-D** — 删除 engine2.py (`git rm`)
5. **IMPORT** — 更新 main.py / scenario_matcher.py / __main__.py 的 import
6. 验证：`python3 -c "from server.ws_server import main; from server.ws_server import pipeline_engine"`

---

## 注意事项

1. **PipelineEngine class 必须保留** — main.py `_ensure_engine()` 返回 PipelineEngine 实例，scenario_matcher 和 __main__.py 都通过它调用方法
2. **engine2 的 `_ensure_engine()` 和 `_ensure_pipeline_manager()` 是转发器** — 合并后移到新 pipeline_engine.py 中
3. **避免循环依赖** — 旧 engine2.py 的 `from .pipeline_engine import PipelineEngine` 在新文件中不能出现
4. **B-5 bug 通过替换逻辑自动修复** — 不需要额外的重写
5. **验证 engine2.py 已无残留引用** — 搜索所有 `.py` 文件中是否还有 `from .engine2` 或 `import engine2`
6. 参考：`server/ws_server/README.md`、`docs/TODO.md` B-5
