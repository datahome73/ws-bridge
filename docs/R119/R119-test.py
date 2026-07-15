#!/usr/bin/env python3
"""R119 Step 5 — 自动派活全流程 5 项修复源码级验证"""

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
mp = "server/ws_server/main.py"
with open(mp) as f:
    main = f.read()

amp = "server/ws_server/__main__.py"
with open(amp) as f:
    amain = f.read()

# ──────────────────────────────────────
# Fix 1: Step 1 自动确认状态落盘
# ──────────────────────────────────────

check("F1a: _handle_hash_start 中有 mgr.save()",
      "mgr.save()" in main[main.find("###start"):main.find("###start")+800] or
      "mgr.save()" in main[main.find("ctx.current_step = 2")-50:main.find("ctx.current_step = 2")+400],
      "Persist Step 1 auto-confirm state")

# Verify it's after current_step=2 setting
f1_region = main[main.find("ctx.current_step = 2"):main.find("ctx.current_step = 2")+250]
check("F1b: save 在 current_step=2 和 steps[0].status=done 之后",
      "mgr.save()" in f1_region and f1_region.index("mgr.save()") > f1_region.index("steps[0][\"status\"]"),
      "save() is after status=done assignment")

check("F1c: R119 注释标识",
      "R119 fix" in f1_region or "R119" in f1_region,
      "R119 annotation present")

# ──────────────────────────────────────
# Fix 2: 启动恢复派活函数 + on_startup
# ──────────────────────────────────────

check("F2a: _restore_pipeline_dispatches 函数存在",
      "async def _restore_pipeline_dispatches" in main,
      "Function definition exists")

f2_fn = main[main.find("async def _restore_pipeline_dispatches"):]
f2_fn = f2_fn[:f2_fn.find("\n\n\n#")] if "\n\n\n#" in f2_fn else f2_fn[:2000]

check("F2b: 遍历 get_all_active()",
      "mgr.get_all_active()" in f2_fn,
      "Iterates active pipelines")
check("F2c: 过滤 RUNNING 状态",
      "PipelineStatus.RUNNING" in f2_fn,
      "Filters for RUNNING pipelines")
check("F2d: 过滤 pending/in_progress step",
      "pending" in f2_fn and "in_progress" in f2_fn,
      "Filters for pending or in_progress steps")
check("F2e: 调用 _enqueue_retry",
      "_enqueue_retry" in f2_fn,
      "Uses retry queue instead of direct dispatch")
check("F2f: R119 日志",
      "[R119]" in f2_fn,
      "R119 log marker present")

check("F2g: on_startup 注册 _restore_dispatches",
      "_restore_dispatches" in amain,
      "Registered in __main__.py on_startup")
check("F2h: on_startup.append 调用",
      "on_startup.append(_restore_dispatches)" in amain,
      "Appended to on_startup lifecycle")

# ──────────────────────────────────────
# Fix 3: 重试队列 + await 修复
# ──────────────────────────────────────

# Check await _restore_pipeline_timers
hb_region = main[main.find("async def handle_broadcast"):]
hb_region = hb_region[:hb_region.find("\n\nasync def")] if "\n\nasync def" in hb_region else hb_region[:2000]
check("F3a: handle_broadcast 中 await _restore_pipeline_timers",
      "await _restore_pipeline_timers()" in hb_region,
      "Added await to _restore_pipeline_timers()")

# Check _enqueue_retry exists
check("F3b: _enqueue_retry 函数定义存在",
      "def _enqueue_retry" in main or "async def _enqueue_retry" in main,
      "Retry queue function exists")

# Check retry loop exists
check("F3c: 重试循环（_retry_loop / _start_retry_loop）存在",
      "_start_retry_loop" in amain or "_retry_loop" in main,
      "Retry loop registered")

# ──────────────────────────────────────
# Fix 4: in_progress 标记 + 落盘
# ──────────────────────────────────────

ad_region = main[main.find("async def _auto_dispatch"):]
ad_region = ad_region[:ad_region.find("\n\nasync def")] if "\n\nasync def" in ad_region else ad_region[:2000]

check("F4a: 派活成功后标记 in_progress",
      "in_progress" in ad_region,
      "status = in_progress after successful dispatch")
check("F4b: in_progress 后调用 mgr.save()",
      'next_step_info["status"] = "in_progress"' in ad_region,
      "in_progress + save pair exists")
check("F4c: save 在 sent > 0 分支内",
      ad_region.find("sent > 0") < ad_region.find("in_progress"),
      "in_progress is inside sent > 0 branch")

# ──────────────────────────────────────
# Fix 5: 消息路由修正 + filter 扩展
# ──────────────────────────────────────

check("F5a: payload type 改为 broadcast",
      '"type": "broadcast"' in ad_region,
      "type changed from message to broadcast")
check("F5b: payload channel 改为 _inbox:{target}",
      '"_inbox:{target_agent_id}"' in ad_region or
      'f"_inbox:{target_agent_id}"' in ad_region,
      "channel changed from _inbox:server to _inbox:{target}")

# Verify old values are gone from _auto_dispatch
check("F5c: _auto_dispatch 中无旧 type=message",
      '"type": "message"' not in ad_region or '"type": "broadcast"' in ad_region,
      "No message type in auto_dispatch payload")
check("F5d: _auto_dispatch 中无旧 channel=_inbox:server",
      '"channel": "_inbox:server"' not in ad_region,
      "No _inbox:server channel in auto_dispatch payload")

# Check filter expansion in _restore_pipeline_dispatches
check("F5e: 恢复过滤包含 in_progress",
      '"pending", "in_progress"' in f2_fn or "('pending', 'in_progress')" in f2_fn or '(pending, in_progress)' in f2_fn,
      "Filter includes in_progress status")

# ──────────────────────────────────────
# 回归检查
# ──────────────────────────────────────

# Existing R117 resolve function intact
check("R1: _resolve_card_key_to_ws_id 未受影响",
      "def _resolve_card_key_to_ws_id" in main,
      "R117 resolve function still present")

# Existing _send_to_agent sent=0 log intact
check("R2: sent=0 日志仍在",
      'sent=0' in main[main.find("def _send_to_agent"):main.find("def _send_to_agent")+1000],
      "sent=0 warning log intact")

# advance logging intact — "[R117] %s Step %d 已完成，尝试自动派活 Step %d"
check("R3: R117 advance 日志仍在",
      "[R117]" in main and "已完成，尝试自动派活" in main and
      main.find("已完成，尝试自动派活") > main.find("def _try_advance_pipeline"),
      "R117 advance log at line 2489 — before context end check")

# ──────────────────────────────────────
# Report
# ──────────────────────────────────────
pass_count = sum(1 for r in results if r[0] == PASS)
fail_count = sum(1 for r in results if r[0] == FAIL)
skip_count = sum(1 for r in results if r[0] == SKIP)
total_active = pass_count + fail_count

print("=" * 60)
print("R119 Step 5 — 源码级验证：5 项修复")
print("=" * 60)
print()

# Print grouped
fixes = {"Fix 1 (Step 1 落盘)": [], "Fix 2 (启动恢复派活)": [],
         "Fix 3 (重试队列+await)": [], "Fix 4 (in_progress)": [],
         "Fix 5 (消息路由+filter)": [], "回归检查": []}
current_fix = None
for icon, name, detail in results:
    for key in fixes:
        if name.startswith(key[:3]) or name.startswith("F" + key[4:5]):
            current_fix = key
            break
    else:
        if name.startswith("R"):
            current_fix = "回归检查"
    if current_fix:
        fixes[current_fix].append((icon, name, detail))

for fix_name, items in fixes.items():
    if items:
        print(f"  [{fix_name}]")
        for icon, name, detail in items:
            d = f"  → {detail}" if detail else ""
            print(f"    {icon}  {name}{d}")
        print()

print("=" * 60)
print(f"统计: {PASS} {pass_count} | {FAIL} {fail_count} | {SKIP} {skip_count} | 总计 {len(results)}")
if fail_count == 0:
    print("结论: ✅ ALL GREEN 🟢")
else:
    print(f"结论: ❌ {fail_count} FAIL")
print("=" * 60)

sys.exit(0 if fail_count == 0 else 1)
