# R104 WORK_PLAN — Web 服务增加工作区列表 API

> **轮次：** R104
> **日期：** 2026-07-13
> **auto_chain:** false
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱

---

## 步骤

### Step 1 — PM 审核确认

需求文档审核通过后，标记已审核，推 dev。

### Step 2 — 架构师（小开）技术方案

评估 `web_viewer.py` 插入点。由于改动简单（+15 行，1 个函数 + 1 条路由），可精简或跳过。

### Step 3 — 开发（爱泰）编码实现

在 `web_viewer.py` 新增 `handle_api_workspaces()` + 在 `setup_routes()` 注册 `/api/workspaces` 路由。

### Step 4 — 审查（小周）代码审查

审查 diff。

### Step 5 — 测试（泰虾）验证

验证 7 项验收标准。

### Step 6 — 部署（小爱）合并 main + 镜像重建

合并 dev→main，重建 Docker 镜像并部署。
