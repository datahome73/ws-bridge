# R74 工作计划 — 管线通用化：WORK_PLAN 单入口 + Raw URL 解耦

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R74/R74-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动局域、严禁 scope creep**

- ✅ 改：`server/handler.py` 中 `_cmd_pipeline_start()` frontmatter 解析逻辑、`_infer_artifact_url()` 的 URL 推断、`_build_pipeline_config()` 的 URL 覆盖
- ✅ 改：`server/config.py` 中 `PIPELINE_STEP_MAP` role 名 `admin` → `operations`
- ✅ 删：`_R62_REPO_BASE` 硬编码常量
- ❌ 不改入：inbox 消息格式、工作室系统、认证体系、Web 前端、状态机流转逻辑
- ❌ 不改出：不引入第三方 YAML 库、不改 `_parse_frontmatter()` 解析器本身

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py` + `server/config.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | `_cmd_pipeline_start()`：frontmatter 缺失 steps 返回错误，不再静默回退 PIPELINE_STEP_MAP | handler.py L2076-2106 | ~8 行 |
| 2 | A1 | `_build_pipeline_config()`：context URL 不再被拼接覆盖，直接使用 frontmatter 的 raw URL | handler.py L1150-1167 | ~5 行 |
| 3 | A1 | 新增 workspace.members 读取：从 frontmatter 解析成员定义 → 传给工作室创建 | handler.py _cmd_pipeline_start 新增分支 | ~10 行 |
| 4 | A2 | `!pipeline_start --work_plan_url` 作为唯一入口参数，仅用于获取 WORK_PLAN 本身而非拼接 | handler.py L2060-2106 | ~3 行 |
| 5 | B1 | 删除 `_R62_REPO_BASE` 常量 | handler.py L1083 | -1 行 |
| 6 | B2 | `_infer_artifact_url()` 增加 step_config 参数，优先读 frontmatter | handler.py L1210-1216 | ~8 行 |
| 7 | C | `PIPELINE_STEP_MAP` role 名 admin→operations | config.py L93-103 | ~2 行 |
| 8 | C | handler.py 中 admin 角色匹配改为 operations | handler.py 多处 | ~5 处 |

**总估算：** ~50 行净增 / -1 行删除 ≈ **49 行净增**

---

## 2. 管线步骤

### Step 1：管线启动 + 配置通知（PM）

**n/a** — PM 在需求审核通过后执行 `!pipeline_start R74 --work_plan_url <raw_url>`

### Step 2：技术方案（Arch）

**主角：** arch / **备用：** dev

**任务：**
阅读需求文档 §2 三个方向（A/B/C），输出技术方案文档 `docs/R74/R74-tech-plan.md`，包含：

1. **方向 A 实现方案**：`!pipeline_start` frontmatter 校验逻辑（无 steps 报错、workspace.members 读取）、`_build_pipeline_config()` context URL 不覆盖
2. **方向 B 实现方案**：`_R62_REPO_BASE` 删除影响分析、`_infer_artifact_url()` 改造
3. **方向 C 实现方案**：admin→operations 全局替换点清单
4. **兼容性分析**：旧轮次（R72/R73 等）的 `_PIPELINE_CONFIG` 已存在，不受影响
5. **每处改动的精确函数名/行号**

**完成条件：** 技术方案文档推 dev + SHA 汇报

### Step 3：编码（Dev）

**主角：** dev / **备用：** arch

**任务：**
按技术方案逐项编码实现。改动集中在 `server/handler.py`：

**A1 — frontmatter 校验（~8 行）**
- 在 `_cmd_pipeline_start()` 的 frontmatter 解析块（L2076-2106），frontmatter 解析成功但无 `steps` → 返回 `❌ 缺少 pipeline.steps 定义`
- 不再走 `_build_fallback_config()`（仅 `--force` 参数保留）

**A1 — workspace.members 读取（~10 行）**
- 从 frontmatter `pipeline.workspace.members` 解析角色 → mention_keyword → rules
- 传给工作室创建逻辑（当前用 `all_roles` 从 step_config 推断）
- 若 frontmatter 中有 workspace.members，优先使用；无则退回到 step_config 推断

**A2 — _build_pipeline_config() context URL 不覆盖（~5 行）**
- 当前 `pipeline` 配置的 `config` dict 中的 `requirements_url` 被 `base_urls` 覆盖
- 改为：frontmatter step context 中已有 URL 字段的，保留不变；空值的才从 base_urls 获取

**B1 — 删除 _R62_REPO_BASE（-1 行）**
- `handler.py` L1083 整行删除
- 删除前确认无其他引用

**B2 — _infer_artifact_url() 增加 step_config 参数（~8 行）**
- 函数签名改为 `def _infer_artifact_url(step_name: str, round_name: str, step_config: dict | None = None) -> str`
- 优先从 `step_config[step_name].get("artifact_url", "")` 读取
- 无配置时走硬编码回退

**B2 — 硬编码 URL 回退从 dev 分支改为 main 分支**
- `_infer_artifact_url` 中的回退 URL 用 `raw.githubusercontent.com/.../main/` 而非 `dev`
- R72/R73 已合入 main，dev 分支已删除

**C — admin→operations 全局替换**
- `config.py` 中 `PIPELINE_STEP_MAP` step1/step6 的 role → operations
- `handler.py` 中所有 `"admin"` 角色匹配 → `"operations"`（排除 admin 命令名称本身）

**完成条件：** 编码完成推 dev + `grep` 零残留验证

### Step 4：审查 ✅ `a914ed0`

**主角：** review / **备用：** qa

**审查重点：**
1. ✅ frontmatter 校验逻辑是否正确——缺 steps 报错，有 steps 正常
2. ✅ `_build_pipeline_config()` 是否还拼接覆盖 context URL
3. ✅ workspace.members 读取逻辑——frontmatter 有则用，无则回退
4. ✅ `_infer_artifact_url()` 优先读 frontmatter，回退硬编码
5. ✅ 删除 `_R62_REPO_BASE` 无其他引用残留
6. ✅ 旧轮次兼容——`!pipeline_status R72` 不应该报错
7. ✅ admin→operations 替换完整——不遗漏不误伤
8. ✅ scope 合规——没有引入不在范围内的改动

**完成条件：** 审查报告推 dev + 🟢 通过

**结论：** 🟢 通过

### Step 5：测试（QA）

**主角：** qa / **备用：** review

**验收清单（从需求文档 §3 复制）：**

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 完整 frontmatter + raw URL → `!pipeline_start` | 管线使用 frontmatter 中的 raw URL，不拼接 | 检查 `_PIPELINE_CONFIG[R74]` 中的 URL 字段 = frontmatter 的 raw URL，非拼接值 |
| ✅-2 | 缺 `pipeline.steps` 的 frontmatter → `!pipeline_start` | ❌ 返回错误 "缺少 pipeline.steps" | 创建无 steps 的 WORK_PLAN → 启动 → 检查错误消息 |
| ✅-3 | frontmatter 定义 `workspace.members` → 成员按定义创建 | 工作室包含相应角色 | frontmatter 定义 arch/dev 两个成员 → 启动后 `!pipeline_status` 成员列表匹配 |
| ✅-4 | 有 `_PIPELINE_CONFIG` 的旧轮次 → `!pipeline_status` | 正常，不报错 | `!pipeline_status R72` → 正常显示 |
| ✅-5 | `_R62_REPO_BASE` 已从 handler.py 删除 | 零匹配 | `grep -n '_R62_REPO_BASE' server/handler.py` → exit=1 |
| ✅-6 | `!pipeline_start` 不拼接 `docs/轮次/` 路径 | 新轮次无 raw URL 的 context 字段为空串而非拼接值 | frontmatter 不配 `requirements_url` → 启动后检查 context 为空 |
| ✅-7 | `_infer_artifact_url` 优先读 frontmatter artifact_url | 自定义 artifact_url 生效 | frontmatter step2 配 `artifact_url: "https://..."` → `!step_complete step2 --summary x` 自动推断为该 URL |
| ✅-8 | 代码中 `role: admin` 全改为 `role: operations` | 零残留 `"admin"` 角色引用 | `grep -n '"admin"' server/handler.py` → 仅排除正常命令名称 |
| ✅-9 | `PIPELINE_STEP_MAP` 中 role 已更新 | step1/step6 role = operations | 检查 `_build_legacy_steps()` 的 role 值 |
| ✅-10 | R74 需求文档不出现 admin 角色名 | 使用 operations/运维 | `grep -n 'admin' docs/R74/R74-product-requirements.md` → 零匹配 |

**完成条件：** 测试报告推 dev + 验收逐项标记 ✅/❌

### Step 6：合并部署归档（Operations）

**主角：** operations / **备用：** arch

**操作：**
1. 合并 dev→main
2. 重新 build Docker 镜像（`docker build`，不是 `docker restart`）
3. 部署生产容器
4. 健康检查（`!pipeline_status R74`）
5. TODO.md 版本号更新
6. 关闭工作室
7. 恢复大厅

---

## 3. 验收清单

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | frontmatter 完整 + raw URL → `!pipeline_start` 正常 | ⏳ |
| ✅-2 | 缺 `pipeline.steps` → ❌ 报错，不回退 | ⏳ |
| ✅-3 | frontmatter `workspace.members` → 成员按定义创建 | ⏳ |
| ✅-4 | 旧轮次 `!pipeline_status` 不报错 | ⏳ |
| ✅-5 | `_R62_REPO_BASE` 零匹配 | ⏳ |
| ✅-6 | 不拼接 `docs/轮次/` 路径 | ⏳ |
| ✅-7 | artifact_url 优先读 frontmatter | ⏳ |
| ✅-8 | admin→operations 全局替换完整 | ⏳ |
| ✅-9 | PIPELINE_STEP_MAP role 更新 | ⏳ |
| ✅-10 | 需求文档零 admin 角色名残留 | ⏳ |

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — R74 WORK_PLAN |
