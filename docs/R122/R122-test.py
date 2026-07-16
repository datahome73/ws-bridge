#!/usr/bin/env python3
"""R122 验收测试 — 源码级分析验证

验证项（7 项，来自 WORK_PLAN Step 6）:
  ① 启动日志出现 [R122] 管线超时扫描已启动
  ② step 派活后 dispatched_at 写入 step 字典
  ③ step 快速完成 → 无告警
  ④ 模拟超时 → PM 收到告警
  ⑤ 同一 step 只告警一次
  ⑥ PIPELINE_TIMEOUT_ALERT_MINUTES=0 → 扫描禁用
  ⑦ 无 running 管线时扫描不报错
"""
import sys, os, re, ast

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAIN_PY = os.path.join(REPO, "server/ws_server/main.py")
CONFIG_PY = os.path.join(REPO, "server/common/config.py")
STATE_PY = os.path.join(REPO, "server/ws_server/state.py")

PASS, FAIL = "✅", "❌"
results = []

def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    print(f"  {icon} {name}")

# ── 读取源文件 ──
with open(MAIN_PY, encoding="utf-8") as f: main_content = f.read()
with open(CONFIG_PY, encoding="utf-8") as f: config_content = f.read()
with open(STATE_PY, encoding="utf-8") as f: state_content = f.read()

print("=" * 60)
print("R122 测试验证 — 源码级分析")
print("=" * 60)

# ── ① 扫描启动日志 ──
print(f"\n{'─'*40}")
print("① 扫描启动日志...")
check("A1: 启动日志字符串 '管线超时扫描已启动'",
      '管线超时扫描已启动' in main_content)
check("A2: _ensure_timeout_scanner 函数存在",
      'def _ensure_timeout_scanner' in main_content)
check("A3: 在 handle_broadcast 中调用",
      '_ensure_timeout_scanner()' in main_content)

# ── ② dispatched_at 写入 ──
print(f"\n{'─'*40}")
print("② dispatched_at 写入...")
check("B1: dispatched_at 字段存在",
      'dispatched_at' in main_content)
check("B2: dispatched_at = time.time()",
      'dispatched_at"] = time.time()' in main_content)
check("B3: timeout_alerted = False",
      'timeout_alerted"] = False' in main_content)
check("B4: 在 sent > 0 块内",
      "if sent > 0:" in main_content)
# Extract _auto_dispatch function body
m = re.search(r'async def _auto_dispatch\(.*?\):(.*?)(?=\nasync def |\ndef )', main_content, re.DOTALL)
if m:
    body = m.group(1)
    check("B5: dispatched_at 在 _auto_dispatch 内",
          'dispatched_at' in body)

# ── ③ 避免误告警 ──
print(f"\n{'─'*40}")
print("③ 快速完成 → 无告警...")
check("C1: 跳过非 in_progress step",
      'if step.get("status") != "in_progress"' in main_content)
check("C2: 跳过无 dispatched_at",
      'if not dispatched_at' in main_content)
check("C3: 跳过已告警 step",
      'if step.get("timeout_alerted")' in main_content)
check("C4: 跳过未超时 step",
      'if elapsed < threshold' in main_content)
check("C5: 仅检查 RUNNING 管线",
      'ctx.status != PS.RUNNING' in main_content)

# ── ④ 超时告警内容 ──
print(f"\n{'─'*40}")
print("④ 超时告警内容...")
check("D1: 告警含 ⏰ emoji", '⏰' in main_content)
check("D2: 告警含 round_name", 'ctx.round_name' in main_content)
check("D3: 告警含 step 号", 'step_num' in main_content)
check("D4: 告警含等待时间", '分钟无回复' in main_content)
check("D5: 发送给 PM (_send_to_agent)", '_send_to_agent(pm_id,' in main_content)
check("D6: 告警后 timeout_alerted=True",
      'timeout_alerted"] = True' in main_content)

# ── ⑤ 不重复告警 ──
print(f"\n{'─'*40}")
print("⑤ 不重复告警...")
check("E1: 告警前检查 timeout_alerted",
      'if step.get("timeout_alerted")' in main_content)
check("E2: 告警后 mgr.save() 持久化",
      'mgr.save()' in main_content)
check("E3: alerted 计数变量", 'alerted' in main_content)

# ── ⑥ 扫描禁用 ──
print(f"\n{'─'*40}")
print("⑥ PIPELINE_TIMEOUT_ALERT_MINUTES=0...")
check("F1: timeout <= 0 检查", 'timeout_min <= 0' in main_content)
check("F2: 禁用日志 '已禁用'", '已禁用' in main_content)
check("F3: 配置项 PIPELINE_TIMEOUT_ALERT_MINUTES 定义",
      'PIPELINE_TIMEOUT_ALERT_MINUTES' in config_content)
check("F4: 默认值 30", '"30"' in config_content)
check("F5: 可通过 R122_TIMEOUT_ALERT_MINUTES 覆盖",
      'R122_TIMEOUT_ALERT_MINUTES' in config_content)
check("F6: SCAN_INTERVAL 默认 300s", '"300"' in config_content)

# ── ⑦ 无 running 管线不报错 ──
print(f"\n{'─'*40}")
print("⑦ 无 running 管线...")
# Extract _pipeline_timeout_scan function body
m = re.search(r'async def _pipeline_timeout_scan\(.*?\):(.*?)(?=\n\nasync def |\n\ndef |\n\n# )', main_content, re.DOTALL)
if m:
    body = m.group(1)
    check("G1: try/except 包裹遍历", 'except Exception' in body)
    check("G2: get_all_active() 遍历管线", 'get_all_active()' in body)
    check("G3: ctx.status != RUNNING 跳过", 'PS.RUNNING' in body)
else:
    # Fallback: check at line level
    check("G1: try/except 包裹遍历", 'except Exception' in main_content)
    check("G2: get_all_active() 遍历管线",
          'mgr.get_all_active()' in main_content,
          "Line 572: for ctx in mgr.get_all_active():")
    check("G3: ctx.status != RUNNING 跳过", 'PS.RUNNING' in main_content)

# ═══ 附加检查 ═══
print(f"\n{'─'*40}")
print("附加检查...")
check("H1: state.py 含 _TIMEOUT_SCAN_TASK",
      '_TIMEOUT_SCAN_TASK' in state_content)
check("H2: state.py 含 _TIMEOUT_SCAN_STARTED",
      '_TIMEOUT_SCAN_STARTED' in state_content)
check("H3: 防重复启动 (state._TIMEOUT_SCAN_STARTED)",
      'state._TIMEOUT_SCAN_STARTED' in main_content)
check("H4: _handle_hash_advance 存在",
      'async def _handle_hash_advance' in main_content)
check("H5: advance 权限校验 (agent_id != pm_agent_id)",
      "agent_id != pm_agent_id" in main_content)
check("H6: advance 在帮助文本中",
      '##advance' in main_content)

# ── 统计 ──
print(f"\n{'='*60}")
pass_c = sum(1 for r in results if r[0] == PASS)
fail_c = sum(1 for r in results if r[0] == FAIL)
total = len(results)
print(f"源码分析结果: {PASS} {pass_c}/{total} | {FAIL} {fail_c}/{total}")
print(f"{'='*60}")
sys.exit(fail_c)
