# R123 调研：Git 提交自动检测管线推进

> **状态：** 📝 调研记录（暂缓实现）
> **日期：** 2026-07-17
> **参与人：** 小谷（PM）+ 项目负责人

---

## 1. 背景

当前管线自动推进依赖 bot 发送精确格式的完成消息：

```
已完成 ✅ R{N} Step {N}
```

这是全自动化链路的单点瓶颈——消息格式不匹配、bot 离线、措辞偏差都会导致管线卡死。R65 已建设 `PipelineGitSync` 类（`server/ws_server/pipeline_sync.py`），可通过检测 git 新提交来自动推进管线，但未接入新管线系统（`PipelineContextManager`），是死代码。

---

## 2. 现状分析：PipelineGitSync（R65）

### 2.1 现有代码位置

`server/ws_server/pipeline_sync.py` — 203 行，包含：

- `PipelineGitSync` 类：`__init__` / `sync()` / `_get_new_commits()` / `_match_commit()` / `_get_commit_files()`
- 模块级状态：`_pipeline_git_locks` / `_pipeline_git_tasks`

### 2.2 4 级匹配规则

| 优先级 | 规则 | 示例命中 |
|:-----:|:-----|:---------|
| 1 | commit message 含 Step 标记 | `feat(R123): Step 3 — xxx` |
| 2 | commit 修改了 Step 配置的产出文件 | `docs/R123/*.md` |
| 3 | commit author 匹配当前 Step 角色 | `author="爱泰"` 在 Step3 的 author 列表 |
| 4 | 兜底（可配置关闭） | 管线活跃期间任意新提交 |

### 2.3 为什么现在是死的

旧 `_pipeline_git_sync_scan()`（`main.py:504-525`）遍历的是 `state._PIPELINE_STATE`（旧 dict 管线系统），而当前管线用的是 `PipelineContextManager`（`pipeline_context.py`），两类数据结构不兼容。

```
state._PIPELINE_STATE（旧）    → PipelineGitSync（死代码）
PipelineContextManager（新）    → 无 git 检测集成
```

---

## 3. 讨论焦点

### 3.1 问题一：Step 3（Dev 编码）不是一次提交

Dev 开发过程中会多次 push（增量提交、修复 bug、重构等），不能在第一轮 commit 就判定"Dev 已完工"。

**结论：git 检测只适用于文档型产出的 step。**

| Step | 角色 | 产出 | 适用 git 检测？ |
|:----:|:-----|:-----|:--------------:|
| 1 | PM | 需求文档 `docs/R123/*.md` | ✅ 一次提交即完成 |
| 2 | Arch | 技术方案 `docs/R123/*.md` | ✅ 一次提交即完成 |
| **3** | **Dev** | **代码实现** | **❌ 迭代提交，不能自动推进** |
| 4 | Review | 审查报告 `docs/R123/*.md` | ✅ 一次提交即完成 |
| 5 | QA | 测试报告 `docs/R123/*.md` | ✅ 一次提交即完成 |
| **6** | **Ops** | **部署操作（无 git 提交）** | **❌ 不适用** |

### 3.2 问题二：Step 6（Ops 部署）无 git 产出

部署操作（merge main、重启容器）产生的是 main 分支的 merge commit，而非 dev 分支。PipelineGitSync 只扫 dev 分支。

**结论：Step 6 保持 bot 完成消息做唯一入口。**

### 3.3 问题三：重复派活/消息风暴风险

如果 git 检测和 bot 完成消息同时触发，会不会给下一步 bot 发两遍派活消息？

**防护方案：双向 guard**

```
git 侧（新）:
    if ctx.current_step != expected_step:
        return  // bot 已先推进，跳过

bot 消息侧（已有，main.py:2607）:
    elif completed_step < old_step:
        return False, "already past"
```

无论谁先触发，另一个会被拦截。同时触发时一个先执行完，另一个被 `step mismatch` 拦截。

---

## 4. 设计方案（暂缓）

### 4.1 按 Step 分治

```
Step 1 (PM 文档)   → git 检测
Step 2 (Arch 方案)  → git 检测
Step 3 (Dev 编码)   → bot 完成消息（原机制不变）
Step 4 (Review 报告) → git 检测
Step 5 (QA 测试报告) → git 检测
Step 6 (Ops 部署)   → bot 完成消息（原机制不变）
```

### 4.2 改造范围

| 文件 | 改动内容 | 预估行数 |
|:-----|:---------|:--------:|
| `pipeline_sync.py` | 改造 `PipelineGitSync.__init__` 接受 `PipelineContext`，新增 `sync_and_advance()` | ~80 |
| `main.py` | 新增 `_pipeline_git_sync_scan_v2()` 遍历 `PipelineContextManager`，注册扫描协程 | ~60 |
| `config.py` | 新增 `GIT_SYNC_STEP_MAP` 配置，控制哪些 step 启用 git 检测 | ~20 |
| 合计 | | ~160 |

### 4.3 完整链路

```
bot 推 git push origin dev
          ↓
扫描协程（每 120s）遍历 PipelineContextManager.get_all_active()
          ↓
    对 status=RUNNING 的管线:
      step 在 GIT_SYNC_STEP_MAP 中 → 执行 git 检测
      step 不在列表中 → 跳过
          ↓
    git fetch origin {branch}
    git log {ctx.last_output_sha}..origin/{branch}
    4 级匹配当前 step
          ↓
    匹配成功:
      1. 更新 ctx.last_output_sha = 新 SHA
      2. 标记当前 step 为 "done"，记录 output={sha, message}
      3. ctx.advance_step()
      4. _auto_dispatch(ctx, next_step)
      5. _notify_pm(ctx, step_num, "dispatched")
```

### 4.4 与现有机制的关系

```
┌─────────────────────────────────────────┐
│           管线推进入口                      │
│                                           │
│  入口 A（新，文档 step 专用）               │
│  git commit → PipelineGitSync → advance  │
│                                           │
│  入口 B（已有，所有 step 均可）             │
│  bot "已完成 ✅ R{N} Step {N}" → advance   │
│                                           │
│  入口 C（已有，紧急手工）                   │
│  PM "##advance##R{N}##step=N"            │
│                                           │
│  兜底告警（已有）                           │
│  30min 超时 → 通知 PM                      │
└─────────────────────────────────────────┘
```

---

## 5. 搁置理由

项目负责人决策：本轮不做。原因：
> 目前太多细节还没讨论清楚。

需要进一步明确的细节：
1. Dev 编码的完成判定标准（除了 bot 手动发消息外还有没有其他方式）
2. Step 6 部署的完成检测方案（是否要扩展 git 检测到 main 分支）
3. 兜底规则的启用条件（`fallback_enabled` 在生产环境是否默认开）
4. 多个 commit 同时到达时的时序处理（git fetch 期间又有新 push）
5. 测试方案：如何模拟 git 提交触发管线推进的端到端测试

---

## 6. 参考资料

- 现有代码：`server/ws_server/pipeline_sync.py`（R65，203 行）
- 旧集成断点：`server/ws_server/main.py:504-525`（`_pipeline_git_sync_scan`）
- 当前管线上下文：`server/ws_server/pipeline_context.py`（`PipelineContext` / `PipelineContextManager`）
- 自动派活逻辑：`server/ws_server/main.py:2775-2880`（`_auto_dispatch`）
- 完成消息解析：`server/ws_server/main.py:2543-2621`（`_try_advance_pipeline`）
