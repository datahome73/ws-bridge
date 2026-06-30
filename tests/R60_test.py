#!/usr/bin/env python3
"""R60 测试 — _get_agent_display() 工具函数 + 5 处替换验证"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0

def check(name: str, cond: bool):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")

handler_path = os.path.join(os.path.dirname(__file__), "..", "server", "handler.py")
with open(handler_path, "r") as f:
    content = f.read()

print("═══ 1. 工具函数定义 ═══")
check("_get_agent_display 函数存在", "def _get_agent_display(agent_id: str) -> str:" in content)
check("优先级: display_name 先检查", "card.get(\"display_name\")" in content)
check("优先级: name 第二", ".get(\"name\")" in content)
check("优先级: role 第三", ".get(\"role\")" in content)
check("回退: agent_id[:12]", "return agent_id[:12]" in content)
check("调用 _load_agent_cards()", "_load_agent_cards()" in content)
check("调用 auth.get_users()", "auth.get_users()" in content)

print("\n═══ 2. 5 处替换验证 ═══")
lines = content.split("\n")

# L205: _handle_auth registration
for i, line in enumerate(lines, 1):
    if 'write_chat_log("系统", f"[注册]' in line:
        check(f"L{i} 注册通知: 已替换 agent_id[:16] → _get_agent_display",
              "_get_agent_display(agent_id)" in line and "agent_id[:16]" not in line)
        break

# L210: _handle_auth admin notify
for i, line in enumerate(lines, 1):
    if '新代理注册请求' in line:
        check(f"L{i} admin通知: 已替换 agent_id[:16] → _get_agent_display",
              "_get_agent_display(agent_id)" in line and "agent_id[:16]" not in line)
        break

# L1803/1820: _send_to_agent
write_chat_matches = 0
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if '[定向通知' in stripped and 'write_chat_log' in stripped:
        if '_get_agent_display(agent_id)' in stripped:
            write_chat_matches += 1
        check(f"L{i} _send_to_agent 定向通知: 已替换 agent_id[:12] → _get_agent_display",
              "_get_agent_display(agent_id)" in stripped and "agent_id[:12]" not in stripped)

# L3414: _notify_member_changed
for i, line in enumerate(lines, 1):
    if 'member_name = _get_agent_display' in line:
        check(f"L{i} _notify_member_changed: 已替换 → _get_agent_display",
              "_get_agent_display(member_id)" in line)
        break

print(f"\n═══ 3. write_chat_log 中 agent_id[:N] 残留扫描 ═══")
residual = 0
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if 'write_chat_log' in stripped:
        for pat in ['agent_id[:16]', 'agent_id[:12]']:
            if pat in stripped:
                print(f"  ❌ L{i}: {stripped[:80]}")
                residual += 1
                FAIL += 1
if residual == 0:
    check("write_chat_log 中无 agent_id[:N] 残留", True)

print(f"\n═══ 4. _notify_member_changed 中 member_id[:12] 残留 ═══")
member_residual = 0
for i, line in enumerate(lines, 1):
    if 'member_id[:12]' in line:
        print(f"  ❌ L{i}: {line[:80]}")
        member_residual += 1
        FAIL += 1
if member_residual == 0:
    check("无 member_id[:12] 残留", True)

print("\n═══ 5. 语法检查 ═══")
import py_compile
try:
    py_compile.compile(handler_path, doraise=True)
    check("Python 语法通过", True)
except py_compile.PyCompileError as e:
    check(f"语法错误: {e}", False)
    FAIL += 1

print(f"\n{'═'*56}")
result = f"结果: ✅ {PASS} / {PASS + FAIL} 通过"
if FAIL == 0:
    result += "  |  🎉 全部通过！"
else:
    result += f"  |  ❌ {FAIL} 失败"
print(result)
sys.exit(0 if FAIL == 0 else 1)
