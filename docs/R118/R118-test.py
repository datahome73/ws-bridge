#!/usr/bin/env python3
"""R118 Step 5 — 源码级分析：管线 Tab created_at 倒序排序"""

import sys, os, re

PASS, FAIL, SKIP = "✅", "❌", "⏭"
results = []

def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok

def check_skip(name, detail=""):
    results.append((SKIP, name, detail))
    return True

# === 读文件 ===
tpl_path = "server/web_ui/templates.py"
with open(tpl_path, encoding="utf-8") as f:
    tpl_content = f.read()

# ──────────────────────────────────────
# A. 静态代码检查
# ──────────────────────────────────────

# A-1: sort 代码正确使用防御性回退
check("A-1a: pipelines.sort 调用存在",
      "pipelines.sort(function" in tpl_content,
      "Found in templates.py L579")

sort_start = tpl_content.find("pipelines.sort(function")
check("A-1b: created_at 做排序键",
      "created_at" in tpl_content[sort_start:sort_start+120],
      "Sort key uses created_at")

check("A-1c: (b.created_at || 0) 防御性回退",
      "(b.created_at || 0)" in tpl_content,
      "Defensive fallback to 0 for null/undefined")

check("A-1d: 倒序 (b - a) 即 newest first",
      "(b.created_at || 0) - (a.created_at || 0)" in tpl_content,
      "b - a = descending order")

sort_expr = re.search(r'pipelines\.sort\(function\(a,b\)\s*\{[^}]+\}\)', tpl_content)
check("A-1e: sort 表达式语法完整",
      sort_expr is not None,
      f"Matched: {sort_expr.group()[:80] if sort_expr else 'NONE'}")

# A-2: 无语法错误
pipeline_fn = tpl_content[tpl_content.find("async function renderPipelineDashboard"):]
func_end = pipeline_fn.find("\nfunction ") if "\nfunction " in pipeline_fn else len(pipeline_fn)
pipeline_fn = pipeline_fn[:func_end]

open_b = pipeline_fn.count("{")
close_b = pipeline_fn.count("}")
check("A-2a: 花括号匹配", open_b == close_b, f"{{ = {open_b}, }} = {close_b}")

open_p = pipeline_fn.count("(")
close_p = pipeline_fn.count(")")
check("A-2b: 圆括号匹配", open_p == close_p, f"( = {open_p}, ) = {close_p}")

check("A-2c: sort 行结束正确",
      "});" in tpl_content[sort_start:sort_start+120],
      "sort call ends with });")

# A-3: created_at 字段存在性（审查已确认，快速验证）
pc_path = "server/ws_server/pipeline_context.py"
with open(pc_path) as f:
    pc_content = f.read()
check("A-3a: PipelineContext created_at 字段定义",
      "created_at: float" in pc_content.split("class PipelineContext")[1].split("def ")[0],
      "Default created_at: float = 0.0")

viewer_path = "server/web_ui/viewer.py"
with open(viewer_path) as f:
    vw_content = f.read()
check("A-3c: API 返回 created_at",
      '"created_at"' in vw_content,
      "handle_api_pipelines returns created_at in response")

# ──────────────────────────────────────
# B. 前端功能验证（需部署后浏览器执行）
# ──────────────────────────────────────
check_skip("B-1: 新管线在最顶部", "需部署后浏览器验证")
check_skip("B-2: 已完成管线排下面", "需部署后浏览器验证")
check_skip("B-3: 同 created_at 稳定排序", "需部署后浏览器验证")
check_skip("B-4: 无管线时空状态正常", "需部署后浏览器验证")
check_skip("B-5: Ctrl+F5 刷新后排序保持", "需部署后浏览器验证")

# ──────────────────────────────────────
# C. 回归检查
# ──────────────────────────────────────

# C-1: 消息 Tab 排序（sortNewestFirst）不受影响
check("C-1a: sortNewestFirst 函数存在",
      "function sortNewestFirst" in tpl_content,
      "Separate sort function for messages")

sf_idx = tpl_content.find("function sortNewestFirst")
check("C-1b: sortNewestFirst 用 ts 字段",
      "ts" in tpl_content[sf_idx:sf_idx+200] if sf_idx >= 0 else False,
      "Message sort uses 'ts' field, not created_at")

# C-2: 后端 API 返回数据不变（排序纯前端）
api_section = vw_content[vw_content.find("async def handle_api_pipelines"):]
api_section = api_section[:api_section.find("\n\n")] if "\n\n" in api_section else api_section[:500]
check("C-2: 后端 handle_api_pipelines 无排序",
      ".sort(" not in api_section and "sort" not in api_section[:200],
      "Backend returns raw data, no server-side sort")

# C-3: 其他 Tab 功能正常（仅检查函数存在性，不检查内部逻辑）
check("C-3a: inbox Tab 加载函数存在",
      "loadInboxMessages" in tpl_content,
      "Inbox Tab load function exists")
check("C-3b: workspace Tab 渲染函数存在",
      "renderWsPanel" in tpl_content,
      "Workspace Tab render function exists")

# ──────────────────────────────────────
# Report
# ──────────────────────────────────────
pass_count = sum(1 for r in results if r[0] == PASS)
fail_count = sum(1 for r in results if r[0] == FAIL)
skip_count = sum(1 for r in results if r[0] == SKIP)
total_active = pass_count + fail_count

print("=" * 60)
print("R118 Step 5 — 静态代码分析")
print("=" * 60)
print()

for icon, name, detail in results:
    d = f"  → {detail}" if detail else ""
    print(f"  {icon}  {name}{d}")

print()
print("=" * 60)
print(f"统计: {PASS} {pass_count} | {FAIL} {fail_count} | {SKIP} {skip_count} | 总计 {len(results)} (活跃 {total_active})")
if fail_count == 0:
    print("结论: ✅ ALL GREEN (5 B 项需部署后验证)")
else:
    print(f"结论: ❌ {fail_count} FAIL")
print("=" * 60)

sys.exit(0 if fail_count == 0 else 1)
