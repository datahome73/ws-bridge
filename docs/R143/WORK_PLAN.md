# R143 跨步状态同步修复轮 — 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **来源文档：** `docs/R143/R143-product-requirements.md`
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

产出：`docs/R143/R143-product-requirements.md` + `docs/R143/WORK_PLAN.md`

| 项 | 状态 |
|:---|:-----|
| 需求文档 | ✅ 已写——单改动：`##advance` 跨步条件修复 |
| WORK_PLAN | ✅ 已写——当前文档 |
| 本地 commit | `dadbaaf` 在 dev 分支 |
| GitHub push | ✅ 已推送 |

---

### Step 2 — 技术方案 🏗️ 小开

产出：`docs/R143/R143-tech-plan.md`

仅 1 项改动，目标明确。以下是实现预分析，供架构师参考：

#### F-1: `##advance` 跨步条件修复 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标函数** | `_handle_hash_advance()` — L1293-L1303 |
| **改动** | 跨步循环条件 `in ("pending",)` → `not in ("done",)`，跳过中间步时清除 `dispatched_at` |
| **行数** | +3/-1（改 1 行条件 + 加 2 行清理） |
| **风险** | 🟢 低——只改变跳步时的状态标记逻辑，不影响正常推进路径 |

**改动前后对比：**

```python
# 当前代码（L1296）：
if step_num_i < step_num and s.get("status") in ("pending",):

# 修复后：
if step_num_i < step_num and s.get("status") not in ("done",):
    s["status"] = "skipped"
    s.pop("dispatched_at", None)  # 清除时间戳，防止超时扫描器误判
```

**语义变化：**

| 条件 | 跳过的状态 | 遗漏的状态 |
|:-----|:-----------|:-----------|
| 旧：`in ("pending",)` | pending | **in_progress** ❌、failed ❌ |
| 新：`not in ("done",)` | pending ✅、in_progress ✅、failed ✅ | 无（done 保留） |

**预检：**
- `_handle_hash_advance` 的 `kv` 参数来自 `##advance##R{N}##step=N` 的 `##k=v` 解析，`step=N` 为必含参数
- `s.get("status")` 的取值：`pending`、`in_progress`、`done`、`failed`、`skipped`、`timeout`
- `s.pop("dispatched_at", None)` 安全——`dispatched_at` 是可选字段，`pop` 带默认值不会 KeyError

---

### Step 3 — 编码 💻 爱泰

#### 前置条件

```bash
cd /opt/data/ws-bridge
git checkout dev
git pull --rebase origin dev          # 同步最新
```

#### 唯一提交：F-1 跨步条件修复（+3/-1 行）

```bash
# 文件：server/ws_server/pipeline_engine.py
# 目标行：L1293-L1303（_handle_hash_advance 函数内）

# 1. 改条件
#   旧：if step_num_i < step_num and s.get("status") in ("pending",):
#   新：if step_num_i < step_num and s.get("status") not in ("done",):

# 2. 追加 dispatched_at 清理
#   在 s["status"] = "skipped" 后追加：
#   s.pop("dispatched_at", None)

# 3. 可选：增强日志信息（便于排查）
#   logger.info("[R143] %s step%d → skipped（##advance 跨步，原状态=%s）",
#               round_name, step_num_i, s.get("status"))

git add -p server/ws_server/pipeline_engine.py
git commit -m "fix(R143): ##advance 跨步时同步跳过 in_progress 中间步

`##advance` 跳步循环仅跳过 `pending` 状态步，遗漏 `in_progress`
中间步，导致超时扫描器发假报警。

- 条件 `in ('pending',)` → `not in ('done',)`（跳过所有未完成的步）
- 被跳过 step 清除 `dispatched_at` 字段（防止超时扫描误判）
- 增强日志：记录原状态名"
```

#### 编码检查清单

| # | 检查项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | Python 语法正确 | `python3 -c "compile(open('server/ws_server/pipeline_engine.py').read(), 'pipeline_engine.py', 'exec'); print('Syntax OK')"` |
| 2 | import 无断裂 | `python3 -c "from server.ws_server import pipeline_engine; print('Import OK')"` |
| 3 | 条件正确性 | 确认 `not in ("done",)` 不会误将 `skipped`/`failed`/`timeout` 步标记为 done |
| 4 | 无 debug print 残留 | `grep -n 'print(' server/ws_server/pipeline_engine.py` |
| 5 | 仅改 _handle_hash_advance 一处 | `git diff` 确认无其他文件的意外改动 |
| 6 | git pull --rebase 后再推送 | 避免覆盖他人提交 |

---

### Step 4 — 代码审查 🔍 小周

产出：`docs/R143/R143-code-review.md`

审查内容：

| # | 检查项 | 说明 |
|:-:|:-------|:-----|
| 1 | 🔍 条件 `not in ("done",)` 不会误跳过 done 步 | done 步不应该被降级为 skipped |
| 2 | 🔍 `s.pop("dispatched_at", None)` 安全 | pop 带默认值，不会因缺少字段而报错 |
| 3 | 🔍 日志信息完整 | 日志含 round_name、step_num_i、原状态 |
| 4 | 🔍 无其他文件的意外改动 | git diff 应只改 _handle_hash_advance 一处 |
| 5 | 🔍 无新硬编码 agent_id | `grep -n 'ws_f26e585f6479\|ws_e9007a4cf802' server/ws_server/pipeline_engine.py` |

---

### Step 5 — Dev 测试 🦐 泰虾

产出：`docs/R143/R143-test-report.md`

验证 **6 项验收标准**（§1.1 验收表）全部通过：

```python
# 测试前准备
# 源码审查级验证——确认改动后的条件语义正确

# ── AS-1: in_progress 中间步 → skipped ──
# 场景：Step 2 in_progress，##advance##R{N}##step=4
# 预期：Step 2 status == "skipped"
# 验证：检查 _handle_hash_advance 中循环条件是否覆盖 "in_progress"

# ── AS-2: done 中间步不被降级 ──
# 场景：Step 2 done，##advance##R{N}##step=4
# 预期：Step 2 status 保持 "done"
# 验证：not in ("done",) → done 步不进入 if 分支

# ── AS-3: 跳过步清除 dispatched_at ──
# 场景：Step 2 in_progress（有 dispatched_at），跳步到 Step 4
# 预期：Step 2 无 dispatched_at 字段
# 验证：s.pop("dispatched_at", None) 在 status = "skipped" 后执行

# ── AS-4: 目标步保持 in_progress ──
# 场景：##advance##R{N}##step=4
# 预期：Step 4 status == "in_progress"（目标步逻辑不变）
# 验证：elif step_num_i == step_num: s["status"] = "in_progress" 未改动

# ── AS-5: pending 中间步正常跳过 ──
# 场景：Step 1 pending，##advance##R{N}##step=4
# 预期：Step 1 → skipped（与修复前一致）
# 验证：not in ("done",) → pending 进入 if 分支

# ── AS-6: 修复后 in_progress 步不触发超时扫描 ──
# 场景：跳步后 Step 2 = skipped
# 预期：_pipeline_timeout_scan 检查 step.get("status") != "in_progress" → 跳过
# 验证：超时扫描器第一筛条件是 status == "in_progress"
```

**测试检查清单：**

| # | 测试项 | 标准 | 类型 |
|:-:|:-------|:-----|:----:|
| 1 | AS-1: in_progress 中间步→skipped | `##advance##R{N}##step=4` 后 in_progress 步变成 skipped | P1 |
| 2 | AS-2: done 中间步不降级 | `##advance` 跳过已完成的步时，done 保持 done | P1 |
| 3 | AS-3: dispatched_at 清除 | 被跳过的步 dispatched_at 字段被删除 | P1 |
| 4 | AS-4: 目标步 in_progress | 目标步正常设为 in_progress | P1 |
| 5 | AS-5: pending 中间步正常跳过 | pending→skipped（与修复前一致） | P1 |
| 6 | AS-6: 不触发超时扫描 | 跳步后 in_progress 的中间步不触发超时告警 | P1 |

---

### Step 6 — 合并 main + 部署 🦸 小爱

```bash
# Step 6a: 合并 dev → main
git checkout main
git merge dev
git push origin main

# Step 6b: 部署到 VPS Docker 容器
# (仅小爱可操作，PM 不写 SSH 命令)
# 部署后需验证：
# 1. 容器启动正常（health check）
# 2. 模拟跨步场景：派活 Step 2 → ##advance##R{N}##step=4 → 无超时假报警

# Step 6c: 标记 R143 完成
git checkout dev
# 更新 TODO.md：
# - B-3/B-4 → 🟢 已修复（R142）✅
# - B-5 → 🟢 降级 P3（bot 静默忽略重复派活）
# - R-1 → 🟢 根因已修复（R143 跨步同步）
```

---

## 注意事项

1. `docs/R*/` 被 `.gitignore` 忽略，需 `git add -f` 强制提交
2. **单改动+3/-1行**——改 1 个条件 + 加 2 行清理 + 无新增函数、无新增配置
3. **回归防护**——`not in ("done",)` 对 done 步无害，pending/in_progress/failed 等未被跳过的状态现在都能正确处理
4. **部署顺序**——先部署到 dev 环境 → QA 验证通过 → 合 main → 部署生产
5. 编码时 `git pull --rebase origin dev` 拉取最新后再推送，避免覆盖他人提交
