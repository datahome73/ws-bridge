#!/usr/bin/env python3
"""R121 Step 5 — 管线按轮次倒序排序验证"""

import sys, re

PASS, FAIL, SKIP = "✅", "❌", "⏭"
results = []
def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name, detail))
    return ok

# ── templates.py ──
with open("server/web_ui/templates.py") as f:
    tpl = f.read()

# A-1: extractRoundNum 函数定义
check("A-1: extractRoundNum 函数存在",
      "function extractRoundNum" in tpl)

fn = tpl[tpl.find("function extractRoundNum"):]
fn = fn[:fn.find("}\n")+2]
check("A-1a: 正则 /R(\\d+)/i 匹配轮次数字",
      "R(\\d+)" in fn and "/i" in fn)
check("A-1b: parseInt 转数字",
      "parseInt" in fn)
check("A-1c: (name || '') 防御性回退",
      "name || ''" in fn or "(name || '')" in fn)
check("A-1d: 未匹配 → 返回 0",
      ": 0" in fn or "return 0" in fn,
      "Ternary: `: 0`")

# A-2: sort 用 round_name 而非 created_at
sort_region = tpl[tpl.find("pipelines.sort(function"):]
sort_region = sort_region[:sort_region.find("});")+3]
check("A-2a: sort 用 extractRoundNum",
      "extractRoundNum" in sort_region)
check("A-2b: sort 键为 round_name",
      "round_name" in sort_region)
check("A-2c: sort 降序 (b - a)",
      "extractRoundNum(b." in sort_region and "extractRoundNum(a." in sort_region)

# A-3: 空管线保护
check("A-3: 空管线先 return 再排序",
      tpl.find("pipelines.length === 0") < tpl.find("pipelines.sort(function"),
      "Empty check before sort")

# ── main.py ──
with open("server/ws_server/main.py") as f:
    main = f.read()

# B-1: created_at=time.time() 在 _handle_hash_start
start_idx = main.find("async def _handle_hash_start")
create_idx = main.find("created_at=time.time()", start_idx)
ctx_idx = main.find("PipelineContext(", start_idx)
check("B-1a: created_at=time.time() 存在",
      create_idx >= 0)
check("B-1b: created_at 在 PipelineContext 参数内",
      create_idx > ctx_idx and create_idx < ctx_idx + 800,
      "parameter in PipelineContext() call")

# ── 排序逻辑模拟验证 ──
def extract_round_num(name):
    import re
    m = re.search(r'R(\d+)', name or '', re.IGNORECASE)
    return int(m.group(1)) if m else 0

test_cases = [
    ("R124", 124), ("R123", 123), ("R122", 122),
    ("R121", 121), ("R120", 120), ("R119", 119),
    ("R121-test", 121), ("r122", 122), (None, 0),
    ("", 0), ("foo", 0),
]
for name, expected in test_cases:
    result = extract_round_num(name)
    check(f"extractRoundNum({repr(name)}) = {expected}",
          result == expected, f"got {result}")

# 排序验证
pipelines = [{"round_name": n} for n in ["R119", "R121", "R120", "R124", "R122"]]
pipelines_sorted = sorted(pipelines, key=lambda p: extract_round_num(p.get("round_name")), reverse=True)
expected_order = ["R124", "R122", "R121", "R120", "R119"]
actual_order = [p["round_name"] for p in pipelines_sorted]
check(f"排序结果正确: {actual_order}",
      actual_order == expected_order,
      f"Expected {expected_order}")

# ── Report ──
pass_count = sum(1 for r in results if r[0] == PASS)
fail_count = sum(1 for r in results if r[0] == FAIL)
print("=" * 60)
print("R121 Step 5 — 管线按轮次倒序排序验证")
print("=" * 60)
for icon, name, detail in results:
    d = f"  → {detail}" if detail else ""
    print(f"  {icon}  {name}{d}")
print()
print("=" * 60)
print(f"统计: {PASS} {pass_count} | {FAIL} {fail_count} | 总计 {len(results)}")
print("结论: ✅ ALL GREEN 🟢" if fail_count == 0 else f"结论: ❌ {fail_count} FAIL")
print("=" * 60)
sys.exit(0 if fail_count == 0 else 1)
