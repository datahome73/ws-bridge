# R110 WORK_PLAN — 自动派活：零手工启动管线 🚀

> **轮次：** R110
> **日期：** 2026-07-13
> **auto_chain:** true
> **auto_start:** true
> **说明：** 新增 PipelineAutoStarter 组件，自动检测新轮次文档 git push、创建 PipelineContext、启动管线、派活 Step 1 给 PM bot。消灭从「需求文档推 dev」到「自动派活 Step 2」之间的 3 次手工操作。
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱

---

## 步骤

### Step 1 — PM 审核确认 ✅

2026-07-13 需求文档审核通过。

**产出：** `docs/R110/R110-product-requirements.md` ✅

---

### Step 2 — 架构师（小开）技术方案

评估以下内容并输出技术方案文档：

1. **PipelineAutoStarter 组件设计** — Git poll 间隔、扫描策略、防重复机制
2. **from_work_plan 工厂方法** — frontmatter 解析（YAML/regex）、模板自动生成规则
3. **角色映射** — 从 Agent Card 读取角色→agent_id，work_plan frontmatter 角色名→系统角色
4. **启动方式** — 作为 asyncio task 注册在 `ws-server/__main__.py`，与 WSS 主循环共存
5. **安全边界** — `git fetch` 只读、`auto_start` 标记守卫、异常隔离
6. **与现有 `!pipeline_start` 命令兼容** — 不破坏手工启动路径

**产出：** `docs/R110/r110-step2-tech-plan.md`

---

### Step 3 — 开发（爱泰）编码实现

详见 Step 2 技术方案。

---

### Step 4 — 审查（小周）代码审查

审查新增组件 + 修改逻辑 + 安全边界。

---

### Step 5 — 测试（泰虾）验证

验证 14 项验收标准（见需求文档 §5）。

---

### Step 6 — 部署（小爱）合并 main + 镜像重建

1. PR: dev → main
2. 重建 Docker 镜像 `ws-bridge:r110`
3. 重启 Supervisor
4. 验证自动派活全链路

---

## 依赖关系

```
Step 1 (PM 审核) ─→ Step 2 (arch 技术方案) ─→ Step 3 (dev 编码) ─→ Step 4 (review 审查) ─→ Step 5 (qa 测试) ─→ Step 6 (ops 部署)
```

---

## 关键文件清单

| 文件 | 改动类型 | 说明 |
|:-----|:---------|:-----|
| `ws-server/pipeline_auto_starter.py` | **新增** | Git poll + 自动检测 + 启动管线 |
| `ws-server/pipeline_context.py` | 修改 | 新增 `from_work_plan()` 工厂方法 |
| `ws-server/__main__.py` | 修改 | 注册 PipelineAutoStarter 作为 asyncio task |
| `ws-server/main.py` | 无需改动 | 复用 `_auto_dispatch` 和 `_try_advance_pipeline` |
| `docs/R110/R110-product-requirements.md` | 新增 | 本需求文档 |
