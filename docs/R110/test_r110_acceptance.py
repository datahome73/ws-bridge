#!/usr/bin/env python3
"""R110 验收测试 — PipelineAutoStarter + from_work_plan 🚀
源码级分析，无需运行服务端。

运行: python3 docs/R110/test_r110_acceptance.py
"""
import os

PROJECT = "/opt/data/ws-bridge"
PASS, FAIL, WARN, SKIP = "✅", "❌", "⚠️", "⏳"
results = []
n = 0


def C(name, ok, detail=""):
    global n
    n += 1
    mark = PASS if ok else FAIL
    results.append((mark, name, detail))
    line = f"  {mark} {name}"
    if detail:
        line += f": {detail}"
    print(line)
    return ok


def S(name, detail):
    global n
    n += 1
    results.append((SKIP, name, detail))
    print(f"  {SKIP} {name}: {detail}")
    return True


def read(path):
    try:
        with open(os.path.join(PROJECT, path)) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def grep(text, pattern):
    return [(i, l) for i, l in enumerate(text.split("\n"), 1) if pattern in l]


def read_fn_body(text, fn_name):
    """Return function body lines given source text and function name."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if fn_name in ln and "def " in ln:
            start = i
            break
    if start is None:
        return []
    # Find next top-level def or class
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith(("def ", "class ", "@")) and not stripped.startswith(
            ("@", "#")
        ):
            # Only stop at top-level def/class (no indent)
            if not lines[i].startswith((" ", "\t")) and stripped.startswith(
                ("def ", "class ")
            ):
                end = i
                break
    return lines[start:end]


def count_in(text, pattern):
    return text.count(pattern)


# ════════════════════════════════════════════════════════════════
print("=" * 60)
print("R110 验收测试 — PipelineAutoStarter + from_work_plan 🚀")
print("=" * 60)
# ════════════════════════════════════════════════════════════════

# ── 1. 文件结构 ────────────────────────────────────────────────
print("\n── 1️⃣ 文件结构 ──")

C("1a: pipeline_auto_starter.py 存在",
  os.path.exists(f"{PROJECT}/server/ws_server/pipeline_auto_starter.py"))
C("1b: from_work_plan() 在 pipeline_context.py",
  "from_work_plan" in read("server/ws_server/pipeline_context.py"))
C("1c: scan_and_start() 注册到 __main__.py",
  "scan_and_start" in read("server/ws_server/__main__.py"))
C("1d: PipelineAutoStarter class 存在",
  "class PipelineAutoStarter" in read("server/ws_server/pipeline_auto_starter.py"))

# ── 2. from_work_plan 工厂方法 ──────────────────────────────────
print("\n── 2️⃣ from_work_plan ──")

pc = read("server/ws_server/pipeline_context.py")
body = read_fn_body(pc, "from_work_plan")
body_text = "\n".join(body)

C("2a: async def 签名", "async def from_work_plan" in pc)
C("2b: 参数 work_plan_path", "work_plan_path" in body_text)
C("2c: 解析 轮次/round", "轮次" in body_text or "round" in body_text)
C("2d: 解析 auto_chain", "auto_chain" in body_text)
C("2e: 解析 角色映射", "角色映射" in body_text or "roles" in body_text)
C("2f: 解析 ### Step N", "Step" in body_text and "re.match" in body_text)
C("2g: 构建 6 步 steps_list",
  all(f"step{i}" in body_text for i in range(1, 7)))
C("2h: 创建 PipelineContext 对象",
  "PipelineContext(" in body_text)
C("2i: 创建后持久化", "self._save()" in body_text or ".save()" in body_text)
C("2j: 支持全角半角 colon",
  ":** " in body_text and "：** " in body_text)
C("2k: 抛出 FileNotFoundError",
  "FileNotFoundError" in body_text)
C("2l: 抛出 ValueError (无轮次)",
  "ValueError" in body_text and "round" in body_text.lower())

# ⏳ R111 暂缓
S("2m: message_templates 自动生成",
  "R111 补 — _generate_message_templates()")
S("2n: references 含 GitHub URL",
  "R111 补 — _generate_references()")
S("2o: 角色 display_name → agent_id 映射",
  "R111 补 — 依赖 Agent Card 体系")

# ── 3. parse_work_plan_meta 解析器 ─────────────────────────────
print("\n── 3️⃣ parse_work_plan_meta ──")

pas = read("server/ws_server/pipeline_auto_starter.py")
p_body = read_fn_body(pas, "parse_work_plan_meta")
pt = "\n".join(p_body)

C("3a: 函数存在", "parse_work_plan_meta" in pas)
C("3b: 返回 round_name", "round_name" in pt)
C("3c: 返回 roles (角色映射)", "roles" in pt)
C("3d: 返回 auto_chain", "auto_chain" in pt)
C("3e: 返回 steps (### 标题)", "steps" in pt)
C("3f: 解析 > **key:** value", "> **" in pt)
C("3g: 兼容全角半角 colon", ":** " in pt and "：** " in pt)
C("3h: 解析 ### Step N 标题", "###" in pt and "re.match" in pt)
C("3i: 空文件返回 {}",
  "not path.exists()" in pt or "return {}" in pt)

# ── 4. find_work_plans 目录扫描 ───────────────────────────────
print("\n── 4️⃣ find_work_plans ──")

ft = "\n".join(read_fn_body(pas, "find_work_plans"))

C("4a: 函数存在", "find_work_plans" in pas)
C("4b: 扫描 docs/ 目录", "docs" in ft and "iterdir" in ft)
C("4c: 只匹配 R{N} 目录", "startswith" in ft and "R" in ft)
C("4d: 检查 WORK_PLAN.md", "WORK_PLAN.md" in ft)
C("4e: 返回 list[Path]", "list[" in ft or ".append" in ft)
C("4f: 目录不存在返回 []",
  "not docs_dir.exists()" in ft or "return []" in ft)

# ── 5. scan_and_start 端到端 ──────────────────────────────────
print("\n── 5️⃣ scan_and_start ──")

st = "\n".join(read_fn_body(pas, "scan_and_start"))

C("5a: async def 签名", "async def scan_and_start" in pas)
C("5b: 参数 mgr", "mgr" in st)
C("5c: 参数 repo_path", "repo_path" in st)
C("5d: 调用 find_work_plans", "find_work_plans" in st)
C("5e: 调用 parse_work_plan_meta", "parse_work_plan_meta" in st)
C("5f: 跳过已存在管线 (mgr.exists)", ".exists(" in st or "exists(" in st)
C("5g: 调用 mgr.from_work_plan", "from_work_plan" in st)
C("5h: 异常隔离 (try/except)", "try" in st and "except" in st)
C("5i: 返回已创建数量 int", "return count" in st or "return 0" in st)
C("5j: 含 pm_inbox_id 参数", "pm_inbox_id" in st)

# ── 6. PipelineAutoStarter 类 ────────────────────────────────
print("\n── 6️⃣ PipelineAutoStarter 类 ──")

C("6a: class 定义", "class PipelineAutoStarter" in pas)
C("6b: __init__ 含 repo_path", "repo_path" in pas)
C("6c: __init__ 含 data_dir", "data_dir" in pas)
C("6d: __init__ 含 pm_agent_id", "pm_agent_id" in pas)
C("6e: __init__ 含 context_mgr", "context_mgr" in pas)
C("6f: start() 方法", "async def start" in pas)
C("6g: stop() 方法", "def stop" in pas)
C("6h: ctx_mgr property",
  "def ctx_mgr" in pas and "@property" in pas)
C("6i: start() 调用 scan_and_start", "scan_and_start" in pas[pas.find("start"):])

# ── 7. __main__.py 注册 ───────────────────────────────────────
print("\n── 7️⃣ __main__.py 注册 ──")

mm = read("server/ws_server/__main__.py")

C("7a: import scan_and_start",
  "from .pipeline_auto_starter import" in mm)
C("7b: 启动时调用 scan_and_start",
  "scan_and_start(" in mm)
S("7c: PipelineAutoStarter 后台轮询",
  "R111 补 — 用户已禁用自动特性")

# ── 8. 语法健康 ──────────────────────────────────────────────
print("\n── 8️⃣ 语法健康 ──")

import subprocess
errors = []
for pf in [
    "server/ws_server/pipeline_auto_starter.py",
    "server/ws_server/pipeline_context.py",
    "server/ws_server/__main__.py",
]:
    r = subprocess.run(
        ["python3", "-c", f"import py_compile; py_compile.compile('{PROJECT}/{pf}', doraise=True)"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        errors.append(f"{pf}: {r.stderr.strip()[:80]}")
C("8a: pipeline_auto_starter.py 语法通过",
   errors == [], "; ".join(errors) if errors else "全部通过")

# ════════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
skipped = sum(1 for r in results if r[0] == SKIP)
total = passed + failed
rate = passed / total * 100 if total else 0

print("\n" + "=" * 60)
print(f"合计: {total} 项 | {PASS} {passed} | {FAIL} {failed} | {SKIP} {skipped} (R111)")
print(f"通过率: {rate:.1f}%")
print("=" * 60)

if failed:
    exit(1)
