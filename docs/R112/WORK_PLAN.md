# R112 — Web 端管线进度可视化（Pipeline Dashboard）📊

> **轮次：** R112
> **auto_chain:** true
> **状态：** ✅ 项目负责人审核通过
> **说明：** 在 Web 端新增「📊 管线」Tab，消费 `pipeline_contexts.json` 数据，展示管线进度条 + Step 状态 + Agent 信息 + 产出链接
> **需求文档：** [R112-product-requirements.md](https://github.com/datahome73/ws-bridge/blob/main/docs/R112/R112-product-requirements.md)
> **审核记录：** v1.0 提交审核 → 2026-07-14 项目负责人 ✅ 通过

---

## 需求文档状态 ✅ 已审核通过

- R112 需求文档已通过项目负责人审核 ✅
- **进入开发流程**

---

## 分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🏗️ 架构师 | 小开 | 技术方案设计 |
| 💻 开发工程师 | 爱泰 | 编码实现（API + 前端 + WebSocket 推送） |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🦸 项目管理 | 小爱 | 部署 + 合并维护 |

---

## 开发步骤

### Step 1 — 需求文档 ✅ 已完成

> 产出：`docs/R112/R112-product-requirements.md`
> 状态：✅ 已审核通过

### Step 2 — 技术方案 🏗️ 架构师（小开）

**产出：** `docs/R112/R112-tech-plan.md`

**需确定的技术细节：**

| # | 议题 | 说明 |
|:-:|:-----|:------|
| 1 | **API 数据源方案** | 直接读 `pipeline_contexts.json` 文件 vs 通过 `PipelineContextManager` 方法 |
| 2 | **WebSocket 广播方案** | 复用 `_broadcast_to_ws` 还是新增 `_broadcast_pipeline_update` |
| 3 | **前端渲染方案** | 纯内嵌 templates.py（当前模式）vs 独立前端文件 |
| 4 | **轮询 vs WebSocket** | 首次加载 API 拉取 + WebSocket 增量推送 |
| 5 | **`to_dict()` 输出字段** | 前端需要哪些字段，补充需要的序列化方法 |

**关键约束：**
- 管线逻辑零改动（`pipeline_context.py` / `handler.py` 不碰）
- Web 端内嵌在 `templates.py` 中（沿用现有架构）
- `PipelineContextManager` 已有 `get_all_active()` + `to_dict()` 可直接用

### Step 3 — 方向审查 🧐 PM（小谷）

确认方案可行后转开发。

### Step 4 — 编码 💻 开发工程师（爱泰）

**改动清单：**

#### 4.1 `server/web_ui/templates.py` — API 端点（~25 行）

```python
@routes.get("/api/pipelines")
async def handle_pipelines_list(request):
    """返回所有管线摘要列表"""
    ...

@routes.get("/api/pipelines/{round_name}")
async def handle_pipeline_detail(request):
    """返回单管线完整详情"""
    ...
```

#### 4.2 `server/web_ui/templates.py` — 前端渲染（~150 行）

- 新增「📊 管线」Tab 的 HTML 面板
- CSS 管线卡片 + 进度条 + Step 状态图标样式
- JS 轮询 + WebSocket 实时更新逻辑
- 响应式布局（桌面 2 列 / 移动 1 列）

#### 4.3 `server/ws_server/main.py` — WebSocket 推送（~20 行）

**4 处插入 `_broadcast_pipeline_update()`：**

| # | 插入位置 | 触发时机 |
|:-:|:---------|:---------|
| 1 | `_handle_hash_start()` | `##start` 创建管线后 |
| 2 | `_try_advance_pipeline()` | Step 推进后 |
| 3 | `_handle_hash_stop()` | `##stop` 停止后 |
| 4 | `_auto_dispatch()` | 派活后（可选，由方案决定） |

#### 4.4 零改动文件

| 文件 | 原因 |
|:-----|:------|
| `pipeline_context.py` | 只读不写，`get_all_active()` + `to_dict()` 已够用 |
| `handler.py` | 不涉及 `!` 命令 |
| `commands/pipeline.py` | 管线命令体系不动 |
| `pipeline_auto_starter.py` | 废弃，不碰 |
| `shared/protocol.py` | 协议不变 |
| `config.py` | 无需新增配置项 |
| `Dockerfile` | 纯 Web 前端改动，templates.py 已内嵌 |

### Step 5 — 代码审查 🔍 审查工程师（小周）

**审查清单：**

| # | 审查项 | 严重度 |
|:-:|:-------|:------:|
| 1 | API 端点不修改管线数据（只读） | 🔴 P0 |
| 2 | WebSocket 推送不阻塞主流程（ensure_future / await） | 🔴 P0 |
| 3 | 前端不硬编码 agent ID / 内部名称 | 🟡 P2 |
| 4 | 新 Tab 不破坏现有大厅/收件箱/历史 Tab 的渲染 | 🟡 P2 |
| 5 | 移动端响应式布局正确 | 🟢 P3 |
| 6 | API 无管线时返回空列表而非 null/error | 🟡 P2 |
| 7 | 长轮次名称在卡片中不溢出 | 🟢 P3 |

### Step 6 — Dev 测试 🦐 测试工程师（泰虾）

**验收项（15 项，见需求文档 §5）：**

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | `GET /api/pipelines` 返回当前所有管线 | curl |
| 2 | `GET /api/pipelines/R112` 返回单管线数据 | curl |
| 3 | 无管线时返回空列表 | curl |
| 4 | 不存在轮次返回 404 | curl |
| 5 | Tab 栏出现「📊 管线」Tab | 浏览器查看 |
| 6 | 活跃管线卡片展示进度条 + Step 状态 | 浏览器查看 |
| 7 | 每步状态图标正确（✅🟢⬜） | 比对 pipeline_contexts.json |
| 8 | 已完成 Step 显示产出链接 | 点链接验证 |
| 9 | `##status` 命令行 vs Web 端状态一致 | 对比 |
| 10 | `##start` 后 Web 端自动出现新卡片 | 3s 内出现 |
| 11 | Step 推进后 Web 端状态自动变化 | 回复 "已完成 ✅" 观察 |
| 12 | `##stop` 后状态变 🛑 CANCELLED | 不刷新观察 |
| 13 | 桌面端 ≥2 列网格 | 1920px 窗口 |
| 14 | 移动端单列堆叠 | 375px 窗口 |
| 15 | 刷新页面后管线数据不丢失 | 刷新后卡片仍在 |

### Step 7 — 上线验证 🦸 项目管理（小爱）

| # | 验证项 | 方法 |
|:-:|:-------|:-----|
| 1 | 生产环境 API 可访问 | curl https://wsim.../api/pipelines |
| 2 | Web 端 📊 Tab 正常渲染 | 浏览器访问 |
| 3 | 启动一条测试管线 `##start##R112-test` | 观察 Web 端实时出现 |
| 4 | 推进 Step 后 Web 端自动更新 | 回复 "已完成 ✅ R112-test Step 1" |
| 5 | 停止测试管线后归档 | `##stop##R112-test` |

### Step 8 — 合并 main + 部署 🦸 项目管理（小爱）

1. 审查通过 + 测试通过 → 合并 dev → main
2. 重建 Docker 镜像 `ws-bridge:r112`
3. 重启生产容器
4. 健康检查通过 ✅

### Step 9 — 关闭工作室 🦸 项目管理（小爱）

- 全员 ACK → 归档轮次文档 → 各成员切回大厅待命

---

## 注意事项

1. **Data 层零改动原则** — R112 只消费 `pipeline_contexts.json` 数据，不创建、不修改、不删除任何管线数据
2. **PM 不参与代码实现** — PM 做 Step 1（已做完）+ 方向审查，不参与 Step 4 编码
3. **`-f` push** — `docs/R*/` 在 `.gitignore` 中，轮次文档需 `git add -f`
4. **先 dev 后 main** — 代码推 dev 分支部署到 dev 环境验证，通过后再合并 main

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — R112 工作计划 |

