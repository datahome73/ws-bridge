"""
R119 Step 5 🦐 测试验证 — 5 项自动派活修复代码验证

Run: python3 -m pytest tests/test_r119_verify.py -v
Or:  python3 tests/test_r119_verify.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = ROOT / "server/ws_server/main.py"
INIT_PY = ROOT / "server/ws_server/__main__.py"

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  🟢 {name}")
    else:
        FAIL += 1
        print(f"  🔴 {name} — {detail}")


def read(path):
    return path.read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# Fix 1: f560daf — Step 1 自动确认状态落盘
# ════════════════════════════════════════════════════════════════
def test_fix1_handle_hash_start_saves():
    """_handle_hash_start must call mgr.save() after setting step1 done."""
    src = read(MAIN_PY)

    # Find the _handle_hash_start function and the relevant section
    # Look for step 1 done marking + mgr.save()
    assert "mgr.save()" in src, "mgr.save() not found in main.py"
    assert "R119 fix" in src or "R119" in src, "R119 marker not found"

    # Find the exact location around step1 auto-confirm save
    m = re.search(
        r'R119 fix.*?落盘.*?try:.*?mgr\.save\(\)',
        src, re.DOTALL
    )
    check("Fix 1: Step1 确认后 mgr.save() 落盘",
          m is not None,
          "mgr.save() not near step1 auto-confirm in _handle_hash_start")


# ════════════════════════════════════════════════════════════════
# Fix 2: 54cc097 — 启动恢复派活框架
# ════════════════════════════════════════════════════════════════
def test_fix2_restore_dispatches_startup_hook():
    """_restore_pipeline_dispatches must be registered as a startup hook."""
    src = read(INIT_PY)

    # Check that the startup hook is registered
    assert "on_startup.append" in src, "No on_startup in __main__.py"

    # Find _restore_dispatches or similar
    m1 = re.search(r'async def _restore_dispatches.*app.*?from \.main import _restore_pipeline_dispatches',
                   src, re.DOTALL)
    m2 = re.search(r'app\.on_startup\.append\(_restore_dispatches\)', src)
    check("Fix 2a: _restore_dispatches startup hook registered",
          m1 is not None and m2 is not None,
          "Missing on_startup hook for _restore_pipeline_dispatches")

    src_main = read(MAIN_PY)
    assert "_restore_pipeline_dispatches" in src_main
    assert "async def _restore_pipeline_dispatches" in src_main
    check("Fix 2b: _restore_pipeline_dispatches() async函数存在",
          "async def _restore_pipeline_dispatches()" in src_main,
          "Function not found or not async")

    # Check it loops over active pipelines
    m3 = re.search(r'for.*ctx.*in.*mgr\.get_all_active\(\)', src_main)
    check("Fix 2c: 遍历 get_all_active() 管线",
          m3 is not None,
          "Missing active pipeline loop")

    # Check it checks RUNNING status
    m4 = re.search(r'ctx\.status.*!=.*PipelineStatus\.RUNNING', src_main)
    check("Fix 2d: 只处理 RUNNING 状态管线",
          m4 is not None,
          "Missing RUNNING status check")

    # Check step bounds
    m5 = re.search(r'step_num.*<.*1.*or.*step_num.*>.*ctx\.total_steps', src_main)
    check("Fix 2e: step 边界检查 (1 <= step_num <= total_steps)",
          m5 is not None,
          "Missing step bounds check")


# ════════════════════════════════════════════════════════════════
# Fix 3: 59acf9a — 改入重试队列 + await 修复
# ════════════════════════════════════════════════════════════════
def test_fix3_enqueue_retry_and_await():
    """_restore_pipeline_dispatches uses _enqueue_retry, not _auto_dispatch directly.
    handle_broadcast awaits _restore_pipeline_timers()."""
    src = read(MAIN_PY)

    # In _restore_pipeline_dispatches: should call _enqueue_retry, not _auto_dispatch
    # Find the block inside _restore_pipeline_dispatches
    m = re.search(
        r'_restore_pipeline_dispatches.*?'
        r'logger\.info\(.*?恢复派活.*?\).*?'
        r'_enqueue_retry\(ctx,\s*step_num\)',
        src, re.DOTALL
    )
    check("Fix 3a: 恢复派活用 _enqueue_retry 而非直接 _auto_dispatch",
          m is not None,
          "Still using asyncio.ensure_future(_auto_dispatch(...)) in _restore_pipeline_dispatches")

    # Check handle_broadcast has await _restore_pipeline_timers()
    m2 = re.search(r'await\s+_restore_pipeline_timers\(\)', src)
    check("Fix 3b: handle_broadcast 中 await _restore_pipeline_timers()",
          m2 is not None,
          "Missing await before _restore_pipeline_timers()")


# ════════════════════════════════════════════════════════════════
# Fix 4: bff10b5 — 成功标记 in_progress
# ════════════════════════════════════════════════════════════════
def test_fix4_dispatch_marks_in_progress():
    """After successful dispatch, step must be marked in_progress + saved."""
    src = read(MAIN_PY)

    # Look for sent > 0 block that marks in_progress
    m1 = re.search(
        r'if sent > 0:.*?'
        r'next_step_info\["status"\].*?=.*?"in_progress".*?'
        r'mgr\.save\(\)',
        src, re.DOTALL
    )
    check("Fix 4a: 派活成功后 step 标记 in_progress + 落盘",
          m1 is not None,
          "Missing in_progress marking after sent > 0 in _auto_dispatch")

    m2 = re.search(
        r'if not step_info or step_info\.get\("status"\) not in \("pending",\s*"in_progress"\)',
        src
    )
    check("Fix 4b: _restore_pipeline_dispatches 也处理 in_progress（重启恢复）",
          m2 is not None,
          "Still only checking 'pending' in _restore_pipeline_dispatches")


# ════════════════════════════════════════════════════════════════
# Fix 5: 5c9e6f0 — auto_dispatch type/channel 修复
# ════════════════════════════════════════════════════════════════
def test_fix5_payload_type_and_channel():
    """auto_dispatch payload must use type=broadcast + channel=_inbox:{bot_id}."""
    src = read(MAIN_PY)

    # Look in _auto_dispatch for the payload dict
    m1 = re.search(
        r'payload = \{\s*'
        r'"type": "broadcast",\s*'
        r'"channel": f"_inbox:\{target_agent_id\}"',
        src
    )
    check("Fix 5a: payload type='broadcast', channel='_inbox:{bot_id}'",
          m1 is not None,
          "Payload still has type='message' or channel='_inbox:server'")

    # Also verify the payload has the other required fields
    m2 = re.search(
        r'"from_name": "小谷",\s*'
        r'"agent_id": "ws_f26e585f6479"',
        src
    )
    check("Fix 5b: payload 含 from_name + agent_id",
          m2 is not None,
          "Missing from_name/agent_id in payload")

    src_init = read(INIT_PY)
    m3 = re.search(r'logging\.basicConfig\(.*?level=logging\.INFO', src_init, re.DOTALL)
    check("Fix 5c: __main__.py 加 logging.basicConfig(INFO)",
          m3 is not None,
          "Missing logging config in __main__.py")


# ════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("R119 Step 5 🦐 5 项自动派活修复 — 代码验证")
    print("=" * 60)
    print()

    tests = [test_fix1_handle_hash_start_saves,
             test_fix2_restore_dispatches_startup_hook,
             test_fix3_enqueue_retry_and_await,
             test_fix4_dispatch_marks_in_progress,
             test_fix5_payload_type_and_channel]

    for t in tests:
        try:
            t()
        except Exception as e:
            FAIL += 1
            print(f"  🔴 {t.__name__} — EXCEPTION: {e}")

    print(f"\ni   {'─' * 50}")
    print(f"    {'🟢' if FAIL == 0 else '🔴'} {PASS}/{PASS + FAIL} passed" +
          (f" ({FAIL} failed)" if FAIL else ""))
    print()

    sys.exit(0 if FAIL == 0 else 1)
