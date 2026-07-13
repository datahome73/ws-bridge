# R109 WORK_PLAN — 架构大重构：ws-server / web-ui 彻底分离 🏗️

> **轮次：** R109
> **日期：** 2026-07-13
> **auto_chain:** false
> **说明：** 将 server/ 拆分为 ws-server/（WSS 核心）+ web-ui/（HTTP 服务），两者零 import 依赖，只在 data/ 目录通过 SQLite/JSON 关联。web 做减法至仅收件箱+历史两个 Tab。WSS config 精简。
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱

---

## 步骤

### Step 1 — PM 审核确认 ✅

2026-07-13 需求文档审核通过。已推送 `be87bc7`，含完整需求 + 减法清单 + 配置文件变更明细。

**产出：** `docs/R109/R109-product-requirements.md` ✅

---

### Step 2 — 架构师（小开）技术方案

评估以下内容并输出技术方案文档：

1. **整体迁移策略** — 分步迁移（先建 web-ui，再建 ws-server，最后删 server/），避免大爆炸
2. **auth.py 拆分** — WSS 认证（api_key/level）vs Web 认证（session/OAuth），拆分边界
3. **message_store.py 只读副本** — 哪些读函数需要复制到 web-ui，哪些可以不走 DB（如归档查询）
4. **persistence.py 拆分** — web-ui 只需 sessions + bind codes，JSON 文件竞争问题（读写锁）
5. **config.py 减法** — 181 行 → ~40 行，具体删除项验证
6. **Bot 状态文件传递** — ws-server 定时写 `data/_bot_status.json`，web-ui 读文件，时序与竞争条件
7. **Dockerfile + supervisor** 更新方案
8. **import 迁移清单** — ws-server 内部 `from .xxx` 不变，web-ui 所有 import 改为本 package 绝对路径

**产出：** `docs/R109/r109-step2-tech-plan.md`

---

### Step 3 — 开发（爱泰）编码实现

详见 Step 2 技术方案。

---

### Step 4 — 审查（小周）代码审查

审查迁移后的目录结构 + import 链 + 功能回归。

---

### Step 5 — 测试（泰虾）验证

验证 22 项验收标准（见需求文档 §5）。

---

### Step 6 — 部署（小爱）合并 main + 镜像重建

1. PR: dev → main
2. 重建 Docker 镜像 `ws-bridge:r109`
3. 重启 Supervisor 双进程
4. 验证 bot 通信 + Web 页面正常

---

## 依赖关系

```
Step 1 (PM 审核) ─→ Step 2 (arch 技术方案) ─→ Step 3 (dev 编码) ─→ Step 4 (review 审查) ─→ Step 5 (qa 测试) ─→ Step 6 (ops 部署)
```

---

## 关键文件清单

| 文件 | 改动类型 |
|:-----|:---------|
| `server/ → ws-server/` | 整个目录重命名 |
| `server/web_service.py → web-ui/__main__.py` | 搬迁 + 重写 import |
| `server/web_viewer.py → web-ui/handlers.py` | 搬迁 + 减法删 handler |
| `server/templates.py → web-ui/templates.py` | 搬迁 + 前端减法 |
| `server/auth.py` 拆分为 `ws-server/auth.py` + `web-ui/auth.py` | 拆分 |
| `server/config.py` 拆分为 `ws-server/config.py` + `web-ui/config.py` | 拆分 |
| `server/message_store.py` → `ws-server/message_store.py` + `web-ui/message_store.py`（只读） | 拆分 |
| `server/persistence.py` → `ws-server/persistence.py` + `web-ui/persistence.py`（仅 sessions/bind） | 拆分 |
| `entrypoint.py` | 删除 |
| `Dockerfile` + `supervisord.conf` | 更新路径 |
