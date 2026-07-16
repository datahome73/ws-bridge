#!/usr/bin/env python3
"""R122 管线超时告警 — 本地集成测试"""
import sys, os, time, asyncio

REPO = "/opt/data/ws-bridge"
sys.path.insert(0, REPO)

import server.ws_server.main as main_mod
from server.common import config as config_mod
from server.ws_server.pipeline_context import PipelineStatus as PS

PASS, FAIL = "✅", "❌"
results = []
alert_log = []

def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    print(f"  {icon} {name}")

def make_ctx(round_name, status, steps):
    class Ctx:
        def __init__(self, n, s, st):
            self.round_name = n
            self.status = s
            self.steps = st
    return Ctx(round_name, status, steps)

def make_step(name, status, dt=None, alerted=False):
    s = {"name": name, "status": status}
    if dt is not None:
        s["dispatched_at"] = dt
        s["timeout_alerted"] = alerted
    return s

class MockMgr:
    def __init__(self):
        self.pipelines = []
        self.saved = False
    def get_all_active(self):
        return self.pipelines
    def save(self):
        self.saved = True

async def mock_send(agent_id, msg):
    alert_log.append({"agent_id": agent_id, "msg": msg})

# Save originals
orig_send = main_mod._send_to_agent
orig_mgr_fn = main_mod._ensure_pipeline_manager
orig_pm = config_mod.PIPELINE_PM_AGENT_ID
orig_timeout = config_mod.PIPELINE_TIMEOUT_ALERT_MINUTES

# Apply patches
main_mod._send_to_agent = mock_send
config_mod.PIPELINE_PM_AGENT_ID = "ws_pm_123"
config_mod.PIPELINE_TIMEOUT_ALERT_MINUTES = 1
mgr = MockMgr()
main_mod._ensure_pipeline_manager = lambda: mgr

now = time.time()

print("=" * 60)
print("R122 — 集成测试")
print("=" * 60)

# ── Test 1: timeout alert ──
print(f"\n{'─'*40}")
print("Test 1: 超时告警触发")
mgr.pipelines = [make_ctx("R122T1", PS.RUNNING, [
    make_step("1", "done"),
    make_step("2", "in_progress", now - 120),
])]
alert_log.clear(); mgr.saved = False
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))

check("T1-1 告警发送", len(alert_log) > 0, f"{len(alert_log)} alerts")
if alert_log:
    c = alert_log[0]["msg"].get("content", "")
    check("T1-2 含 ⏰", '⏰' in c, "")
    check("T1-3 含轮次", 'R122T1' in c, "")
    check("T1-4 含 Step", 'Step' in c or 'step' in c.lower(), "")
    check("T1-5 发给 PM", alert_log[0]["agent_id"] == "ws_pm_123", "")
check("T1-6 timeout_alerted 标记", mgr.pipelines[0].steps[1].get("timeout_alerted") == True, "")
check("T1-7 mgr.save() 调用", mgr.saved, "")

# ── Test 2: no repeat ──
print(f"\n{'─'*40}")
print("Test 2: 不重复告警")
alert_log.clear(); mgr.saved = False
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
check("T2-1 不重复", len(alert_log) == 0, "")

# ── Test 3: not timed out ──
print(f"\n{'─'*40}")
print("Test 3: 未超时不告警")
mgr.pipelines = [make_ctx("R122T3", PS.RUNNING, [
    make_step("1", "in_progress", now - 10),
])]
alert_log.clear()
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
check("T3-1 未超时不告警", len(alert_log) == 0, "")

# ── Test 4: completed pipeline ──
print(f"\n{'─'*40}")
print("Test 4: COMPLETED 管线不扫描")
mgr.pipelines = [make_ctx("R122T4", PS.COMPLETED, [
    make_step("1", "in_progress", now - 120),
])]
alert_log.clear()
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
check("T4-1 COMPLETED 跳过", len(alert_log) == 0, "")

# ── Test 5: no dispatched_at ──
print(f"\n{'─'*40}")
print("Test 5: 旧数据无 dispatched_at")
mgr.pipelines = [make_ctx("R122T5", PS.RUNNING, [
    make_step("1", "in_progress", None),
])]
alert_log.clear()
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
check("T5-1 无时间戳跳过", len(alert_log) == 0, "")

# ── Test 6: empty pipelines ──
print(f"\n{'─'*40}")
print("Test 6: 空管线列表")
mgr.pipelines = []
alert_log.clear()
try:
    asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
    check("T6-1 空列表不报错", True, "")
except Exception as e:
    check("T6-1 空列表不报错", False, str(e))

# ── Test 7: no PM configured ──
print(f"\n{'─'*40}")
print("Test 7: 无 PM 配置时不告警但标记")
config_mod.PIPELINE_PM_AGENT_ID = ""
mgr.pipelines = [make_ctx("R122T7", PS.RUNNING, [
    make_step("1", "in_progress", now - 120),
])]
alert_log.clear()
asyncio.run(main_mod._pipeline_timeout_scan(timeout_min=1))
check("T7-1 无 PM 不告警", len(alert_log) == 0, "")
# The timeout_alerted flag is set OUTSIDE the `if pm_id:` block
check("T7-2 仍标记 timeout_alerted", mgr.pipelines[0].steps[0].get("timeout_alerted") == True, "")

# ── Restore ──
main_mod._send_to_agent = orig_send
main_mod._ensure_pipeline_manager = orig_mgr_fn
config_mod.PIPELINE_PM_AGENT_ID = orig_pm
config_mod.PIPELINE_TIMEOUT_ALERT_MINUTES = orig_timeout

# ── Summary ──
print(f"\n{'='*60}")
pass_c = sum(1 for r in results if r[0] == PASS)
fail_c = sum(1 for r in results if r[0] == FAIL)
total = len(results)
print(f"结果: {PASS} {pass_c}/{total} | {FAIL} {fail_c}/{total}")
sys.exit(fail_c)
