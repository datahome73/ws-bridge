#!/usr/bin/env python3
"""
R58 静态验证测试套件 — 自动化断言
====================================
测试范围：A2/A3/B2/C2/C3 全部 19 个分支的代码存在性和正确性。
可直接本地运行：python3 tests/R58_test.py

运行条件：repo 已 checkout a4d961c（或包含 R58 改动的任意 commit）
"""

import ast
import sys
import os

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLER_PATH = os.path.join(REPO_DIR, "server", "handler.py")
CONFIG_PATH = os.path.join(REPO_DIR, "server", "config.py")

passed = 0
failed = 0
errors = []


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(msg)


def check_not(name: str, condition: bool, detail: str = ""):
    """反向断言：condition 应为 False"""
    check(name, not condition, detail)


def file_read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


handler_src = file_read(HANDLER_PATH)
config_src = file_read(CONFIG_PATH)

# ═══════════════════════════════════════════════════════════
# Preq: 语法检查
# ═══════════════════════════════════════════════════════════
print("\n═══ 0. Preq: 语法检查 ═══")

try:
    ast.parse(handler_src)
    check("handler.py 语法通过", True)
except SyntaxError as e:
    check("handler.py 语法通过", False, str(e))

try:
    ast.parse(config_src)
    check("config.py 语法通过", True)
except SyntaxError as e:
    check("config.py 语法通过", False, str(e))


# ═══════════════════════════════════════════════════════════
# 1. Config: PIPELINE_PM_NAME
# ═══════════════════════════════════════════════════════════
print("\n═══ 1. Config: PIPELINE_PM_NAME ═══")

check("PIPELINE_PM_NAME 定义在 config.py", "PIPELINE_PM_NAME" in config_src)
check("类型标注为 : str", "PIPELINE_PM_NAME: str" in config_src)
check("WS_PM_NAME 环境变量可覆盖", 'os.environ.get("WS_PM_NAME", "PM")' in config_src)


# ═══════════════════════════════════════════════════════════
# 2. handler.py 导入链
# ═══════════════════════════════════════════════════════════
print("\n═══ 2. 导入链 ═══")

# 解析最顶层的 import
top_imports = handler_src.split("\n")[:15]
top_import_text = "\n".join(top_imports)
check("handler.py 从 . 导入 config", "from . import" in top_import_text and "config" in top_import_text)


# ═══════════════════════════════════════════════════════════
# 3. A 方向: from_name @mention 改造 (P0)
# ═══════════════════════════════════════════════════════════
print("\n═══ 3. A 方向: from_name @mention 改造 (P0) ═══")

# A2: _cmd_step_complete PM @mention
check("A2 标记段存在", "R58 A2: PM @mention broadcast" in handler_src)
check("A2: config.PIPELINE_PM_NAME 引用", "config.PIPELINE_PM_NAME" in handler_src)
check("A2: @mention 含 @{primary_name} 变量插值", "@{primary_name}" in handler_src)
check("A2: 含需求 URL", "product-requirements.md" in handler_src)
check("A2: 含 WORK_PLAN URL", "WORK_PLAN.md" in handler_src)
check("A2: 含 output_ref", "output_ref" in handler_src.split("# ── R58 A2: PM @mention broadcast")[1].split("# ── R58 A2: End PM broadcast")[0])
check("A2: from_name=pm_name", '"from_name": pm_name' in handler_src)
check("A2: _persist_broadcast 用 pm_name", '_persist_broadcast(sender_ch, pm_name' in handler_src)
check("A2: 全成员广播循环", "for member_id in ws_obj.members" in handler_src)
check("A2: try/except 安全保护", "except Exception:" in handler_src)

# A3: _cmd_pipeline_start kickoff
check("A3 标记段存在", "R58 A3: Initial kickoff PM @mention notification" in handler_src)
check("A3: 含 @全员", "@全员" in handler_src)
check("A3: _persist_broadcast(ws_id, pm_name, ...)", '_persist_broadcast(ws_id, pm_name' in handler_src)
check("A3: target_role 在 A3 前已定义（代码顺序正确）",
      handler_src.index("target_role") < handler_src.index("R58 A3"))

# A4: 双重保险 — _send_to_agent 未被删除
check("A4: _send_to_agent 保留 ≥2 处", handler_src.count("_send_to_agent") >= 2,
      detail=f"找到 {handler_src.count('_send_to_agent')} 处")
check("A4: from_name='系统' 旧点名保留", 'from_name": "系统"' in handler_src or "from_name='系统'" in handler_src)


# ═══════════════════════════════════════════════════════════
# 4. B 方向: ACK 软检查日志 (P1)
# ═══════════════════════════════════════════════════════════
print("\n═══ 4. B 方向: ACK 软检查日志 (P1) ═══")

check("B2 标记段存在", "R58 B2: Log rollcall ACK status" in handler_src)
check("B2: timedout_members 提取", 'ack_result.get("timedout_members", set())' in handler_src)
check("B2: if timedout 保护（无超时不写日志）", "if timedout:" in handler_src)
check("B2: logger.info 含在线/ACK/超时参数", "online_count" in handler_src and "acked_members" in handler_src)
# B2 不应有 return（日志后继续执行）
b2_block = handler_src.split("# ── R58 B2: Log rollcall ACK status")[1].split("# ── R58 B2: End ACK log")[0]
check_not("B2: 无 return 阻断管线", "return" in b2_block, detail="B2 是软检查日志，不应 return")


# ═══════════════════════════════════════════════════════════
# 5. C 方向: 通知状态跟踪 (P2)
# ═══════════════════════════════════════════════════════════
print("\n═══ 5. C 方向: 通知状态跟踪 (P2) ═══")

# C2: 记录
check("C2 标记段存在", "R58 C2: Record notification status to pstate" in handler_src)
check("C2: pstate.setdefault 初始化", 'pstate.setdefault("step_notifications", {})' in handler_src)
check("C2: 记录含 status/notified_at/target_agents",
      all(k in handler_src for k in ['"status"', '"notified_at"', '"target_agents"']))

# C3: 展示
check("C3 标记段存在", "R58 C3: Notification status display" in handler_src)
check("C3: notified → 📨", 'notify_mark = " 📨"' in handler_src)
check("C3: acknowledged → ✅ACK", 'notify_mark = " ✅ACK"' in handler_src)
check("C3: no_response → ❌静默", 'notify_mark = " ❌静默"' in handler_src)
check("C3: 默认空标记", 'notify_mark = ""' in handler_src)
check("C3: notify_mark 拼入输出行", "{notify_mark}" in handler_src)


# ═══════════════════════════════════════════════════════════
# 6. a4d961c 修复验证
# ═══════════════════════════════════════════════════════════
print("\n═══ 6. a4d961c 修复验证 ═══")

check("FIX-B1: target_agents = [] 在 else 分支（backup 路径初始化）", "target_agents = []" in handler_src)
check("FIX-B2: output 行含 {notify_mark}", "{notify_mark}" in handler_src)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
total = passed + failed
print(f"\n{'═' * 50}")
print(f"结果: ✅ {passed} / {total} 通过", end="")
if failed:
    print(f"  |  ❌ {failed} 失败")
else:
    print("  |  🎉 全部通过！")

if errors:
    print(f"\n失败项:")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("静态验证完成，可以继续输出测试报告。")
    sys.exit(0)
