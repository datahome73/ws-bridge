#!/usr/bin/env python3
"""R113 Step 6 — 管线自动派活修复 测试验证 🔧
源码级分析 + AST 语法校验，无需跑服务端。
运行: cd /opt/data/ws-bridge && python3 docs/R113/test_r113_acceptance.py
"""
import os, sys, py_compile

PROJECT = "/opt/data/ws-bridge"
PASS, FAIL = "✅", "❌"
results = []
n = 0

def C(name, ok, detail=""):
    global n; n += 1
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    d = f": {detail}" if detail else ""
    print(f"  {icon} #{n}. {name}{d}")
    return ok

def read(path):
    with open(os.path.join(PROJECT, path)) as f:
        return f.read()

print("=" * 60)
print("R113 — 管线自动派活修复 验收测试")
print("=" * 60)

pc = read("server/ws_server/pipeline_context.py")
main = read("server/ws_server/main.py")

print("\n── T1: INIT→RUNNING 转换 ──")
ok = "PipelineStatus.RUNNING" in pc.split("INIT: {")[1].split("}")[0] if "INIT: {" in pc else False
C("INIT→RUNNING 转换已添加", ok)

print("\n── T2: from_dict .get() 后备 ──")
bad_keys = ['"round_name"', '"task_kind"', '"workspace_dir"', '"task_dir"', '"status"']
from_dict_section = pc.split("return cls(")[1].split("created_at")[0] if "return cls(" in pc else ""
all_get = True
for k in bad_keys:
    line = [l for l in from_dict_section.split("\n") if k in l]
    has_get = any(".get(" in l for l in line)
    if not has_get:
        C(f"  from_dict 仍有 d[{k}] 直接访问", False, f"行: {line}")
        all_get = False
C("from_dict 全部5字段 .get() 替换", all_get)

print("\n── T3: except KeyError, ValueError ──")
load_block = pc.split("def _load")[1].split("def _append")[0] if "def _load" in pc else ""
for exc in ["KeyError", "ValueError"]:
    C(f"_load() except 含 {exc}", exc in load_block)

print("\n── T4: steps 搜索 None 防护 ──")
search_line = [l for l in main.split("\n") if "ctx.steps or []" in l]
C("step 搜索含 ctx.steps or []", len(search_line) > 0)

print("\n── T5: pipeline_context.py AST 语法 ──")
try:
    py_compile.compile(os.path.join(PROJECT, "server/ws_server/pipeline_context.py"), doraise=True)
    C("pipeline_context.py 语法正确", True)
except py_compile.PyCompileError as e:
    C("pipeline_context.py 语法正确", False, str(e))

print("\n── T6: main.py AST 语法 ──")
try:
    py_compile.compile(os.path.join(PROJECT, "server/ws_server/main.py"), doraise=True)
    C("main.py 语法正确", True)
except py_compile.PyCompileError as e:
    C("main.py 语法正确", False, str(e))

print("\n" + "=" * 60)
p = sum(1 for r in results if r[0] == PASS)
f = sum(1 for r in results if r[0] == FAIL)
print(f"\n📊  总计: {len(results)} 项 | {PASS} {p}/{len(results)} | {FAIL} {f}/{len(results)}")
if f > 0:
    print("\n── 失败项 ──")
    for icon, name, detail in results:
        if icon == FAIL:
            print(f"  {name}  {detail}")
print(f"\n结果: {'ALL GREEN 🟢' if f == 0 else f'{f} 项未通过 — 详见测试报告'}")
