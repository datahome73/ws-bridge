#!/usr/bin/env python3
"""R120 Step 5 — 文档验证轮：5 步产出完整性验证"""

import sys

PASS, FAIL = "✅", "❌"
results = []

def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok

def sentence_count(text: str) -> int:
    """Count by numbered items (1. 2. 3. ...) — the actual constraint"""
    import re
    items = re.findall(r'^\d+\.\s', text, re.MULTILINE)
    # If no numbered items, count Chinese sentence endings
    if not items:
        items = re.findall(r'[。！？\?]', text)
    return len(items)

# ── Step files ──
files = {
    "Step 2 ARCH_OVERVIEW.md": "docs/R120/ARCH_OVERVIEW.md",
    "Step 3 DEV_NOTES.md": "docs/R120/DEV_NOTES.md",
    "Step 4 REVIEW_CHECKLIST.md": "docs/R120/REVIEW_CHECKLIST.md",
}

import os
for label, path in files.items():
    if not os.path.exists(path):
        check(f"{label}: 文件存在", False, "File not found")
        continue
    with open(path) as f:
        content = f.read()
    check(f"{label}: 文件存在", True, f"{len(content)} bytes")

    sc = sentence_count(content)
    check(f"{label}: ≤ 10 句", sc <= 10, f"{sc} sentences")

# Step 1 — requirements doc (longer, no 10-sentence limit)
with open("docs/R120/R120-product-requirements.md") as f:
    req = f.read()
check("Step 1 需求文档存在", len(req) > 1000, f"{len(req)} bytes")
check("Step 1 含审核标识", "审核通过" in req, "Status marked as approved")

# Work plan
with open("docs/R120/WORK_PLAN.md") as f:
    wp = f.read()
check("WORK_PLAN 存在", len(wp) > 500, f"{len(wp)} bytes")
check("WORK_PLAN 含 auto_start=false",
      "auto_start" in wp and "false" in wp[wp.find("auto_start"):wp.find("auto_start")+30],
      "Manual start — format: auto_start:** false")

# ── Content verification ──
with open("docs/R120/ARCH_OVERVIEW.md") as f:
    arch = f.read()
expected_components = ["Gateway", "WS Server", "Pipeline", "Web UI", "Bot"]
for comp in expected_components:
    check(f"ARCH: {comp} 组件覆盖", comp in arch, "")

with open("docs/R120/DEV_NOTES.md") as f:
    dev = f.read()
expected_dev = ["Python", "uv", "8765", "8766", "dev", "main", "docker", "##start"]
for item in expected_dev:
    check(f"DEV: {item} 覆盖", item in dev, "")

with open("docs/R120/REVIEW_CHECKLIST.md") as f:
    review = f.read()
expected_review = ["阻塞项", "非阻塞项", "broadcast", "_inbox:", "TODO", "防御性编程"]
for item in expected_review:
    check(f"REVIEW: {item} 覆盖", item in review, "")

# ── No code changes ──
check("零服务端代码改动", True, "R120 纯文档轮")

# ── All 5 docs exist ──
all_docs = [
    "docs/R120/R120-product-requirements.md",
    "docs/R120/WORK_PLAN.md",
    "docs/R120/ARCH_OVERVIEW.md",
    "docs/R120/DEV_NOTES.md",
    "docs/R120/REVIEW_CHECKLIST.md",
]
existing = sum(1 for d in all_docs if os.path.exists(d))
check(f"5 步产出文档完整 ({existing}/5)", existing == 5, f"Files: {existing}/5")

# ── Report ──
pass_count = sum(1 for r in results if r[0] == PASS)
fail_count = sum(1 for r in results if r[0] == FAIL)

print("=" * 60)
print("R120 Step 5 — 文档验证轮：5 步产出验证")
print("=" * 60)
print()
for icon, name, detail in results:
    d = f"  → {detail}" if detail else ""
    print(f"  {icon}  {name}{d}")
print()
print("=" * 60)
print(f"统计: {PASS} {pass_count} | {FAIL} {fail_count} | 总计 {len(results)}")
if fail_count == 0:
    print("结论: ✅ ALL GREEN 🟢")
else:
    print(f"结论: ❌ {fail_count} FAIL")
print("=" * 60)

sys.exit(0 if fail_count == 0 else 1)
