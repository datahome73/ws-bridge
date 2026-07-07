# R74 产品需求 — 管线参数化完善：frontmatter 唯一配置源 🎯

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-07
> **基线：** `85b5615`（main 最新）
> **本轮改动范围：** `server/handler.py` + `server/config.py`
> **参考：** docs/ARCHITECTURE-REQUIREMENTS.md §6 P0「管线参数化完善」

---

## 0. 先验验证：R62-R69 管线基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| `_parse_frontmatter()` 函数 | ✅ | `handler.py` L1107 — 解析 WORK_PLAN YAML frontmatter |
| `_build_pipeline_config()` 函数 | ✅ | `handler.py` L1150 — 从 frontmatter 构建 `_PIPELINE_CONFIG` |
| `_get_step_config()` 统一读取 | ✅ | `handler.py` L1229 — 优先 frontmatter，回退硬编码 |
| `_build_fallback_steps()` 回退 | ✅ | `handler.py` L1238 — 从 `PIPELINE_STEP_MAP` 构建 fallback |
| `_PIPELINE_CONFIG[round_name]` 持久化 | ✅ | 管线启动时创建，运行时内存保持 |
| `PIPELINE_STEP_MAP` 硬编码 | ✅ 仍存在 | `config.py` L91 — 6 步硬编码作为全局默认值 |
| **总结** | ✅ | 管线基础设施就绪，但 frontmatter 仍为可选 |

---

## 1. 问题背景

### 1.1 现状：frontmatter 是可选配置，PIPELINE_STEP_MAP 是静默后门

当前管线启动逻辑（`handler.py` L2076-2106）的工作流：

```
!pipeline_start R{N}
  ├─ 有 WORK_PLAN.md + 有 frontmatter ✅ → 用 frontmatter 驱动
  ├─ 有 WORK_PLAN.md + 无 frontmatter → 静默回退到 PIPELINE_STEP_MAP
  └─ 无 WORK_PLAN.md → 静默回退到 PIPELINE_STEP_MAP（打印一条日志）
```

这意味着：

1. **无 frontmatter 也能启动管线** — 依赖 6 步硬编码，轮次只能做「6 步软件开发管线」
2. **新轮次无法定义自定义 Step 链** — 不能创建 3 步或 8 步管线，不能换角色名
3. **PIPELINE_STEP_MAP 是副作用代码** — `config.py` 定义了 `primary`/`backup` 等字段，但这些仅被 `_build_fallback_*` 使用，生产管线（有 frontmatter 的轮次）从不碰它
4. **新轮次启动时零反馈** — 如果 WORK_PLAN.md 忘记写 frontmatter，管线静静回退，不报错不提醒

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | R62 设计为渐进迁移 | 当时将 frontmatter 设计为「可选增强」而非「唯一源」，保留向后兼容 |
| 2 | 至今无轮次尝试自定义 Step 链 | 所有轮次停留 6 步管线，未暴露 frontmatter-only 约束的缺失 |
| 3 | PIPELINE_STEP_MAP 无清理触发条件 | 一直有人引用（fallback 函数），无人 clean up |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **P0 方向** | ARCHITECTURE-REQUIREMENTS.md §6 标记「管线参数化完善」为 P0，「R62 已建骨架，需持续迭代使新轮次可完全定义自己的 Step 数/角色/超时」 |
| 🟡 **遗留代码债** | PIPELINE_STEP_MAP + `_build_fallback_*` 共 ~80 行仅用于旧格式退化，新轮次永不触及。清理后可减少 ~50 行死代码 |
| 🟢 **改动小且局域** | 仅改 `handler.py` 中 `!pipeline_start` 的 frontmatter 处理逻辑 + `_get_step_config` 回退控制。单函数主逻辑，不影响管线运行时 |

---

## 2. 功能需求

### 设计原则

> **Frontmatter 成为管线配置的唯一来源。** 新轮次必须在 WORK_PLAN.md 中包含 `pipeline:` frontmatter 定义 Step 链，否则 `!pipeline_start` 返回明确错误。旧已归档轮次通过已有的 _PIPELINE_CONFIG 内存数据继续运行——不破坏已完成管线的状态查询。

---

### 方向 A（核心）：`!pipeline_start` 要求 frontmatter 🔴 P0

#### A1 — 无 frontmatter 时返回明确错误，不再静默回退

**位置：** `handler.py` L2076-2106（`_cmd_pipeline_start` 中 frontmatter 解析块）

```python
# 当前逻辑：
#   ① 尝试解析 frontmatter → 成功就用
#   ② 失败或不存在 → 静默回退到 PIPELINE_STEP_MAP（写一条日志）

# 改造后逻辑：
#   ① 尝试解析 frontmatter → 成功就用 → 继续
#   ② 失败 → 检查该轮次是否有已有 _PIPELINE_CONFIG（已归档/恢复场景）
#      ├─ 有已有配置 → 复用（不报错，兼容已有管线状态查询）
#      └─ 无已有配置 → 返回 ❌ "{round_name} 的 WORK_PLAN.md 缺少 pipeline: frontmatter 配置"
```

**关键行为对比：**

| 场景 | 当前 | 改造后 |
|:-----|:-----|:-------|
| 新轮次 ✅ 有 frontmatter | 用 frontmatter | 用 frontmatter ✅ 不变 |
| 新轮次 ❌ 无 frontmatter | 静默回退到 6 步 | ❌ 返回明确错误 |
| 旧轮次（已有 _PIPELINE_CONFIG） | 复用已有配置 | ✅ 复用已有配置（不影响已完成的管线） |
| `!pipeline_status` 查询旧轮次 | 正常 | ✅ 正常（不走 frontmatter 解析，直接从已有 config 读） |

#### A2 — 新增 `--force` 参数绕过 frontmatter 检查（管理员调试用）

对于已知没有 frontmatter 但需要启动管线做临时调试的场合：

```
!pipeline_start R{N} --force
```

`--force` 触发 `_build_fallback_config()` 生成 6 步默认配置。这不是生产路径，仅供调试/演示。

---

### 方向 B（辅助）：支持自定义 Step 数量与角色 🟡 P1

#### B1 — 确认 `_get_step_config()` 和 `_step_sort_key()` 已支持任意 step 数量

当前 `_step_sort_key()` 支持 `step1..stepN` 的自然排序，`_get_step_config()` 直接从 `_PIPELINE_CONFIG` 返回 frontmatter steps。读取端已具备多 Step 能力。

需要确认的消费点（均通用，无需改造）：

| 消费点 | 位置 | 通用性 |
|:-------|:-----|:-------|
| `step_keys = sorted(step_config.keys(), key=_step_sort_key)` | L1427 | ✅ 通用 |
| `next_role = step_config[next_step].get("role", "")` | L1497 | ✅ 通用 |
| `timeout_min = step_config.get(next_step, {}).get("timeout_minutes", 20)` | L1523 | ✅ 通用 |
| `_build_pipeline_config(frontmatter, ...)` | L2089 | ✅ 通用（frontmatter 自己定义步数） |

**结论：** B1 为确认性验证，成立即通过。

#### B2 — `_infer_artifact_url()` 不再假设固定 step 映射

**位置：** `handler.py` L1210-1216

```python
# 当前：step_urls 硬编码 step2/step4/step5
step_urls = {
    "step2": f"...tech-plan.md",
    "step4": f"...review-report.md",
    "step5": f"...test-report.md",
}

# 改造后：优先从 frontmatter 的 step_cfg 中读取 artifact_url_template
# 如果 step_cfg 没有 artifact_url 配置，才尝试硬编码推断
```

**改动：** `_infer_artifact_url()` 增加参数 `step_config: dict`，优先从 frontmatter 的 step 配置中读 `artifact_url` 字段（若有定义）。无定义时维持当前硬编码回退。

---

### 方向 C（辅助）：清理死代码 🟢 P2

#### C1 — 移除 `PIPELINE_STEP_MAP` 公共常量

**位置：** `config.py` L91-103

移除 `PIPELINE_STEP_MAP` 字典定义（~12 行）。将 `_override_raw` + `PIPELINE_STEP_MAP.update(override)` 保留为 `_LEGACY_STEP_MAP_OVERRIDE`（仅 `--force` 路径使用）。

**前置检查：**

```bash
grep -rn 'PIPELINE_STEP_MAP' server/ --include='*.py'
# 应只剩 handler.py 中的 _build_fallback_steps/_build_fallback_config 引用
```

#### C2 — `_build_fallback_config()` / `_build_fallback_steps()` 仅 `--force` 路径可调用

保留函数，但改名 `_build_legacy_config()` / `_build_legacy_steps()`。所有非 `--force` 调用点改为错误返回。

---

## 3. 验收标准

### 🎯 3.1 方向 A

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 有 frontmatter 的 WORK_PLAN.md → `!pipeline_start` | 正常启动，从 frontmatter 读取 Step 配置 | 发 `!pipeline_start R74` → 检查 `_PIPELINE_CONFIG[R74]` 含 frontmatter 定义的 steps |
| ✅-2 | 无 frontmatter 的 WORK_PLAN.md → `!pipeline_start` | 返回 ❌ 缺少 frontmatter 错误 | 发 `!pipeline_start R{N}`（无 frontmatter）→ 检查返回错误消息 |
| ✅-3 | 已有 `_PIPELINE_CONFIG` 的旧轮次 → `!pipeline_status` | 正常显示，不报错 | `!pipeline_status R72` → 显示正常状态 |
| ✅-4 | `--force` 参数 → 无 frontmatter 也能启动 | 成功启动，用 legacy 6 步配置 | `!pipeline_start R{N} --force` → 管线正常启动 |

### 🎯 3.2 方向 B

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-5 | frontmatter 定义 3 个 Step → 管线只运行 3 步 | `!pipeline_status` 显示 3 步，无 step4/5/6 | 定义 frontmatter 含 step1/step2/step3 → 启动 → 查看状态 |
| ✅-6 | frontmatter 定义自定义角色名 → 点名匹配自定义角色 | `!pipeline_status` 显示角色名（非传统 5 角色） | 定义 `step2: {role: "researcher"}` → 检查状态显示 |
| ✅-7 | `_infer_artifact_url()` 优先读 step_config.artifact_url | 自定义 step 配了 `artifact_url` 后自动推断正确 | frontmatter 定义 step2 含 `artifact_url` 字段 → `!step_complete step2` 自动推断 |
| ✅-8 | `_infer_artifact_url()` 无自定义配置时维持旧推断 | 未定义 artifact_url 的 step2/4/5 仍用现有硬编码 URL | 旧格式 frontmatter → `!step_complete step2 --summary "done"` → artifact_url 为默认 tech-plan URL |

### 🎯 3.3 方向 C

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-9 | `config.py` 中移除 `PIPELINE_STEP_MAP` | 文件不再有该常量 | `grep -n 'PIPELINE_STEP_MAP' server/config.py` → 零匹配 |
| ✅-10 | `handler.py` 全局不再引用 `config.PIPELINE_STEP_MAP` | 仅 legacy 函数内有引用 | `grep -n 'PIPELINE_STEP_MAP' server/handler.py` → 仅 2 处 |
| ✅-11 | `--force` 路径使用 legacy 配置正常 | force 启动后管线状态正常 | `!pipeline_start R{N} --force` → `!pipeline_status` 显示 6 步 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 并行 Step 支持 | 多个 Step 同时执行 | 架构 P2 方向，非本轮范围 |
| 自定义 Step 状态机 | 非线性流转（step1→step2→step3） | 涉及状态机核心改造，范围过大 |
| Web 管线仪表盘 | 前端 Step 进度可视化 | 架构 P1 方向，需独立轮次 |
| 验证钩子系统 | Step 完成后的自动脚本验证 | 架构 P1 方向，需独立轮次 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** `_cmd_pipeline_start` frontmatter 解析逻辑（L2076-2106） | ~10 行 |
| `server/handler.py` | **修改** `_infer_artifact_url()` 增加 step_config 参数（L1210-1216） | ~8 行 |
| `server/handler.py` | **重构** fallback 函数 → legacy-only | ~5 行 |
| `server/handler.py` | **新增** `--force` 参数解析 | ~5 行 |
| `server/handler.py` | **修改** `_get_step_config()` 新轮次无 frontmatter 报错 | ~5 行 |
| `server/config.py` | **删除** `PIPELINE_STEP_MAP` 常量（L91-103） | -12 行 |
| `server/config.py` | **保留** override 逻辑为 `_LEGACY_STEP_MAP_OVERRIDE` | ~3 行 |
| **合计** | | **~36 行净增 / -12 行删除 ≈ 24 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 正在运行的管线引用了 fallback 函数 | 代码改后运行时崩溃 | ① 旧已运行管线通过 `_PIPELINE_CONFIG` 不再走 fallback ② `--force` 保留 legacy 路径 |
| 其他文件引用了 `config.PIPELINE_STEP_MAP` | import 报错 | 推前 `grep -rn 'PIPELINE_STEP_MAP' server/` 全景确认 |

---

## 6. 脱敏检查清单

- [ ] docs/R74/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R74/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / admin）
- [ ] 不包含真实 agent_id / token / URL

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — R74 管线参数化完善：frontmatter 唯一配置源 |
