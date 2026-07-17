# R124 Step 4 — 代码审查报告

> **审查人：** 👁 小周（Review）
> **审查依据：** `docs/R124/R124-product-requirements.md` v1.0 + `docs/R124/R124-tech-plan.md` v1.0
> **审查范围：** `server/ws_server/main.py` (+245/-75), `server/common/config.py` (+2), `gateway-plugin/__init__.py` (+14)
> **审查 Commits：** `856a6ed` + `a2a7dfe` + `b9c19c3`
> **审查日期：** 2026-07-17
> **审查结论：** 🔴 **不通过 — 2 Critical 需修复**

---

## 🔴 F-1（Critical）— 代码重复：两个函数各定义两次

**位置:** `server/ws_server/main.py`

### _handle_reject

| 出现位置 | 行数 | 特点 | 状态 |
|:---------|:----:|:-----|:----:|
| L2950 | 49行 | 简易版：缺 `"stuck"` 守卫、缺第4次退回→stuck逻辑、无 `_notify_pm` | ❌ 被覆盖 |
| L3498 | 173行 | **完整版**：含 stuck 处理、PS.COMPLETED 导入、详细 PM 通知 | ✅ 生效 |

### _archive_pipeline

| 出现位置 | 行数 | 特点 | 状态 |
|:---------|:----:|:-----|:----:|
| L2999 | 44行 | 内含重复 `from pathlib import Path` | ❌ 被覆盖 |
| L3838 | 52行 | **完整版**：含完整归档逻辑 | ✅ 生效 |

**根因:** Codex 在文件不同位置插入了同组函数两次，第二次定义在 Python 中覆盖第一次。

**影响:** 运行时无错误（Python 用最后定义），但 L2950-L3068 区间成为死代码，严重损害可维护性。

**修复:** 删除 L2950-L3068 区间（第一次 `_handle_reject` + 第一次 `_archive_pipeline` + 其中的 `from pathlib import Path`）。

---

## 🔴 F-2（Major）— ##help 未更新 ##archive

**位置:** `server/ws_server/main.py`, `_handle_hash_cmd` 的 `##help` 分支

**问题:** 命令路由已注册 `##archive`，但 `##help` 输出文本中未列出该命令。用户执行 `##help` 看不到 archive 可用。

**修复:** 在 `##help` 输出中添加 `"##archive##R{N} — 归档管线（PM使用）\\n"`。

---

## 🟡 W-1（Minor）— 缺少 R124 专用测试

| 新增函数 | 功能 | 风险 |
|:---------|:-----|:----:|
| `_handle_reject` | 驳回回退逻辑（rollback 索引、4次 stuck 阈值） | 🔴 关键路径无防护 |
| `_archive_pipeline` | 归档序列化/反序列化/文件 I/O | 🟡 数据持久化 |
| `_verify_sha_remote` | 异步 git 验证（超时/异常路径） | 🟢 可选 |
| `_auto_re_notify` | 超时重发派活 | 🟢 异常路径 |

**建议:** 至少为 `_handle_reject` 的 rollback 索引计算和 `_archive_pipeline` 的文件存储写独立测试。

---

## 🟡 W-2（Minor）— `_fmt_ts` 辅助函数位置不当

`_fmt_ts` 定义在文件中部紧接 `_find_archive`，被 `_handle_hash_status` 调用。建议后续整理时将辅助函数集中。

---

## ✅ 通过项

### 驳回处理（需求 A）✅
- 正则匹配 `退回 🔄 R{N} Step {N}` ✅
- 终端状态守卫（stuck/PS.COMPLETED）✅
- rollback 起点：Step 1/2→Step2, Step 3+→Step3 ✅
- 后续步 output/status/result_msg 重置 ✅
- 第 4 次退回标记 stuck ✅
- 原因提取：全角`—`/半角`--`/`-` 三种分隔符 ✅
- PM 通知含操作指引 ✅

### 管线归档（需求 B）✅
- 完成时自动归档 ✅
- 归档 JSON 含完整上下文（steps/artifacts/references/summary）✅
- >50 条 trim 到 30 ✅
- ctx pop 后引用仍有效（Python 对象引用持久）✅
- 手动归档 `##archive##R{N}`（PM 权限校验正确）✅

### 产出验证（需求 C）✅
- SHA 格式正则 `[0-9a-f]{7,40}` ✅
- 远程 git 异步验证 5s 超时 ✅
- 不阻塞主线推进（`asyncio.ensure_future`）✅
- PIPELINE_OUTPUT_VERIFICATION 默认关，环境变量可控 ✅

### 超时增强（需求 D）✅
- 30min 告警（R122）保留 ✅
- 30min 重发派活（R124 新增）✅
- 45min timeout 标记（R124 新增）✅
- 阶梯式顺序正确：告警→重发→标记 ✅

### Gateway Auth Retry ✅
- 6 次重试 × 5s 间隔 ✅
- auth_ok 时重置计数器 ✅
- 超限后 stop reconnecting ✅
- 崩溃后自动恢复（`continue`）✅

### 向后兼容 ✅
- 已有函数签名未修改 ✅
- PipelineContext 序列化结构未改 ✅
- R122/R115 代码不受影响 ✅

---

## 审查 Checklist

| # | 验收项 | 优先级 | 状态 |
|:-:|:-------|:-----:|:----:|
| A-1 | 驳回消息匹配 Regex | 🟢 | ✅ |
| A-2 | 驳回回退到正确位置 | 🟢 | ✅ |
| A-3 | 回退前清除后续步状态 | 🟢 | ✅ |
| A-4 | 驳回原因提取 | 🟡 | ✅ |
| A-5 | 第 4 次驳回标记 stuck | 🟡 | ✅ |
| B-1 | 管线完成时自动归档 | 🟢 | ✅ |
| B-2 | 归档 JSON 含完整上下文 | 🟢 | ✅ |
| B-3 | 归档文件 trim 逻辑 | 🟡 | ✅ |
| B-4 | 手动归档 ##archive | 🟡 | ✅ |
| C-1 | SHA 格式验证正则 | 🟢 | ✅ |
| C-2 | 远程 git 验证异步不阻塞 | 🟢 | ✅ |
| C-3 | 配置环境变量化 | 🟢 | ✅ |
| D-1 | 30min 重发派活 | 🟢 | ✅ |
| D-2 | 45min timeout 标记 | 🟡 | ✅ |
| D-3 | Gateway auth 重试 | 🟡 | ✅ |
| E-1 | 代码无重复定义 | 🟢 | ❌ F-1 |
| E-2 | ##help 包含所有已注册命令 | 🟡 | ❌ F-2 |
| E-3 | 新增功能有测试覆盖 | 🔵 | ❌ W-1 |

---

## 合并建议

修复 **F-1**（删除 L2950-L3068 死代码区间）和 **F-2**（更新 `##help` 添加 `##archive`）后即可合并。建议 W-1/W-2 追踪到 TODO。

> **审查结论：** 🔴 不通过（2 Critical）
> **F-1/F-2 修复：** 💻 爱泰（等待 PM 派活）
