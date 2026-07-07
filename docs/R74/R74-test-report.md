# R74 测试报告 — 管线通用化：WORK_PLAN 单入口 + Raw URL 解耦

> **测试人：** 🦐 泰虾
> **测试对象：** commit `9b2354e`
> **审查报告：** `d5e2a15`
> **测试日期：** 2026-07-07
> **测试方法：** 源码级静态分析（`grep` + 代码逻辑追溯）

---

## 测试结论

**🟢 12/12 全部通过** — 可以进入 Step 6 合并部署

---

## 验收清单

| # | 检查项 | 测试方法 | 结果 | 证据 |
|:-:|:-------|:---------|:----:|:-----|
| ✅-1 | 完整 frontmatter + raw URL → `!pipeline_start` 正常 | 代码路径追溯 | 🟢 **通过** | `_PIPELINE_CONFIG.get(round_name)` 缓存命中跳过重建（L2096）；`_build_pipeline_config()` 用 `if not config.get(...)` 仅填充空字段，不覆盖 frontmatter 值（L1159-1164）；R74 WORK_PLAN 包含完整 `steps` → 通过 steps 校验（L2113-2120） |
| ✅-2 | 缺 `pipeline.steps` → ❌ 报错 | 校验逻辑追溯 | 🟢 **通过** | L2113: `psteps = config_data.get("steps", {})` → 空 dict 被 `not psteps` 捕获 → L2115-2120 返回 `❌ 缺少 pipeline.steps 定义`；`--force` 参数可绕过（L2114: `and not force_flag`） |
| ✅-3 | frontmatter `workspace.members` → 成员按定义创建 | 成员解析代码追溯 | 🟢 **通过** | L2170: `workspace_members_fm = pconfig.get("workspace", {}).get("members", {})` → 有定义时用 `workspace_members_fm.keys()` 作为 `all_roles`；匹配 card 按 display_name 匹配 mention_keyword（L2183-2190）；无 card 用户按角色回退（L2195-2198） |
| ✅-4 | 旧轮次 `!pipeline_status` 不报错 | 缓存路径追溯 | 🟢 **通过** | L2096: `_pipeline_config = _PIPELINE_CONFIG.get(round_name)` → 缓存命中则跳过 frontmatter 加载；`NoFrontmatterError` 走 `_build_fallback_config()`（L2127） |
| ✅-5 | `_R62_REPO_BASE` 已删除 | `grep -rn '_R62_REPO_BASE' server/` | 🟢 **通过** | exit=1，零匹配 ✅；已被 `config.WORK_PLAN_REPO_URL` 替代（L1158 等） |
| ✅-6 | 不拼接 `docs/轮次/` 路径 | `_build_pipeline_config()` 代码追溯 | 🟢 **通过** | L1159-1164: 仅条件补缺（`if not config.get(...)`），无路径拼接；旧 `_R62_REPO_BASE` + `f"/docs/{round_name}/..."` 拼接已完全移除 |
| ✅-7 | `_infer_artifact_url` 优先读 frontmatter | 函数逻辑追溯 | 🟢 **通过** | L1222-1226: `if step_config and step_name in step_config:` → 优先读 `artifact_url` → 非空即返回；无配置走 `main` 分支硬编码回退（L1232-1238） |
| ✅-8 | admin→operations 全局替换完整 | grep 核查 | 🟢 **通过** | `server/config.py`: PIPELINE_STEP_MAP step1 `role: operations` ✅, step6 `primary: operations` ✅；handler.py 中 `"admin"` 保留处均为系统级 admin 权限检查（如 L157 角色检查、L4321 收件箱权限），非管线角色，符合「排除 admin 命令名称」规则 |
| ✅-9 | PIPELINE_STEP_MAP role 已更新 | 配置核查 | 🟢 **通过** | `server/config.py` L93: `"step1": {"role": "operations", ...}`; L102: `"step6": {"role": "manager", "primary": "operations", ...}` |
| ✅-10 | 需求文档零 admin 角色名残留 | `grep -n 'admin' docs/R74/R74-product-requirements.md` | 🟢 **通过** | `feedback_channel: "_admin"` 为频道名称（系统 `_admin` 命令频道），非角色名；L63 提及 `admin` 系记录历史问题，非当前角色定义 |
| ✅-11 | PM inbox 发送任务成功 | 权限逻辑追溯 | 🟢 **通过** | L4321: `if sender_role != "admin" and not _is_any_workspace_admin(sender_id):` — PM (非 admin) 作为 workspace admin 可发收件箱消息 |
| ✅-12 | 角色名不匹配时 display_name fallback | 匹配逻辑追溯 | 🟢 **通过** | L2183-2190: `card_name in keywords` 子串匹配 display_name；匹配失败时 L2195-2198 按 `u.get("role", "member") in all_roles` 兜底；`seen` 集防重复（L2193） |

---

## 审查建议跟进

| # | 建议 | 跟进状态 |
|:-:|:-----|:---------|
| 💡 1 | `step_config.get(step_name, {}).get(...)` 可简化 `step_config[step_name].get(...)` | ⏳ 后续清理（L1222 有 `step_name in step_config` 前置保障，功能正确） |
| 💡 2 | `step_config = _get_step_config(round_name)` 出现两次 | ⏳ 后续优化 |
| 💡 3 | `card_name in keywords` 子串匹配可改成 `keyword == card_name` 更精确 | ⏳ 后续优化（当前场景单值 display_name 等效精确匹配） |

---

## 改动统计

| 文件 | 行变动 |
|:----|:------:|
| `server/handler.py` | +101 / -42 |
| `server/config.py` | +6 / -0 |
| **合计** | **+107 / -42 (净增 65 行)** |

> 注：`server/web_viewer.py` + `server/templates.py` 的变动来自 R74 范围外的消息排序修复，非 R74 管线通用化改动。

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — 12/12 ✅ 全绿通过 |
