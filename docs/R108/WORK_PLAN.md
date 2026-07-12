# R108 WORK_PLAN — 自动派活全链路验证

> **轮次：** R108 | **auto_chain:** true
> **round_title:** 新增 /api/version 端点

## Steps

### Step 1 — PM
需求审核完毕，推送 dev。

### Step 2 — 小开 (arch) 技术方案
产出 docs/R108/r108-step2-tech-plan.md

### Step 3 — 爱泰 (dev) 编码
server/web_viewer.py 新增 /api/version handler

### Step 4 — 小周 (review) 审查
审查 web_viewer.py diff

### Step 5 — 泰虾 (qa) 测试
6 项验收标准

### Step 6 — 小爱 (ops) 部署
合并 main + 重建镜像
