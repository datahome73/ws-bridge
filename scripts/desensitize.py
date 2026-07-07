#!/usr/bin/env python3
"""
R75 Desensitization Script — internal name → generic role name replacement.

Usage:
  python3 scripts/desensitize.py                    # execute replacements
  python3 scripts/desensitize.py --check            # dry-run only
  python3 scripts/desensitize.py --check --verbose  # dry-run with per-file details

Replacement map (longer strings first to avoid partial-match issues):
  小谷 → 需求分析师
  小爱 → 项目管理
  小开 → 架构师
  爱泰 → 开发工程师
  小周 → 审查工程师
  泰虾 → 测试工程师
  大宏 → 项目负责人
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Replacement Map (longer strings first) ──────────────────────────────
NAME_MAP = [
    ("小谷", "需求分析师"),
    ("小爱", "项目管理"),
    ("小开", "架构师"),
    ("爱泰", "开发工程师"),
    ("小周", "审查工程师"),
    ("泰虾", "测试工程师"),
    ("大宏", "项目负责人"),
]
NAME_MAP.sort(key=lambda x: -len(x[0]))  # longest first to avoid partial match

# ── Agent ID Pattern ────────────────────────────────────────────────────
AGENT_ID_RE = re.compile(r"ws_[0-9a-f]{12}")

# ── Archive marker ──────────────────────────────────────────────────────
ARCHIVE_MARKER = (
    "> **状态：** 🏁 已归档\n"
    "> **备注：** 历史轮次，代码已合并入 main。保留供参考。\n"
)


def find_work_plan_files():
    """Find all WORK_PLAN.md under docs/R*/"""
    docs_dir = os.path.join(REPO_ROOT, "docs")
    files = []
    for entry in sorted(os.listdir(docs_dir)):
        entry_path = os.path.join(docs_dir, entry)
        if os.path.isdir(entry_path) and entry.startswith("R"):
            wp_path = os.path.join(entry_path, "WORK_PLAN.md")
            if os.path.isfile(wp_path):
                files.append(wp_path)
    return files


def replace_internal_names(content):
    """Replace internal names with generic role names."""
    for old, new in NAME_MAP:
        content = content.replace(old, new)
    return content


def clean_agent_ids(content):
    """Replace ws_[0-9a-f]{12} with <agent_id>."""
    return AGENT_ID_RE.sub("<agent_id>", content)


def add_archive_marker(content):
    """Add archive marker after frontmatter if not already present."""
    if "🏁 已归档" in content:
        return content
    if content.startswith("---"):
        parts = content.split("---\n", 2)
        if len(parts) >= 3:
            body = parts[2]
            return f"{parts[0]}---\n{parts[1]}---\n{ARCHIVE_MARKER}\n{body}"
    # No frontmatter — insert at top
    return f"{ARCHIVE_MARKER}\n{content}"


def scan_work_plan_files(check_only=False, verbose=False):
    """Scan/replace internal names in WORK_PLAN.md files."""
    files = find_work_plan_files()
    total_name_hits = 0
    total_agent_hits = 0
    results = []

    for path in files:
        rel = os.path.relpath(path, REPO_ROOT)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if check_only:
            name_hits = sum(content.count(old) for old, _ in NAME_MAP)
            agent_hits = len(AGENT_ID_RE.findall(content))
            if name_hits or agent_hits:
                results.append((rel, name_hits, agent_hits))
                total_name_hits += name_hits
                total_agent_hits += agent_hits
            continue

        new_content = replace_internal_names(content)
        if new_content != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            name_hits = sum(content.count(old) for old, _ in NAME_MAP)
            agent_hits = len(AGENT_ID_RE.findall(content))
            results.append((rel, name_hits, agent_hits))
            total_name_hits += name_hits
            total_agent_hits += agent_hits

    return results, total_name_hits, total_agent_hits


def scan_all_docs_agent_ids(check_only=False, verbose=False):
    """Scan/replace agent_ids in ALL docs/ .md files."""
    docs_dir = os.path.join(REPO_ROOT, "docs")
    total_hits = 0
    results = []

    for root, dirs, files in os.walk(docs_dir):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, REPO_ROOT)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            hits = AGENT_ID_RE.findall(content)
            if not hits:
                continue

            total_hits += len(hits)
            results.append((rel, len(hits)))
            if not check_only:
                new_content = AGENT_ID_RE.sub("<agent_id>", content)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)

    return results, total_hits


def archive_old_rounds(check_only=False, verbose=False):
    """Add 🏁 archive marker to R34-R44 WORK_PLAN.md files."""
    docs_dir = os.path.join(REPO_ROOT, "docs")
    total = 0
    results = []

    for num in range(34, 45):  # R34 to R44 inclusive
        wp_path = os.path.join(docs_dir, f"R{num}", "WORK_PLAN.md")
        if not os.path.isfile(wp_path):
            continue
        rel = os.path.relpath(wp_path, REPO_ROOT)
        with open(wp_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "🏁 已归档" in content:
            continue

        total += 1
        results.append(rel)
        if not check_only:
            new_content = add_archive_marker(content)
            with open(wp_path, "w", encoding="utf-8") as f:
                f.write(new_content)

    return results, total


def main():
    check_only = "--check" in sys.argv
    verbose = "--verbose" in sys.argv

    # Phase 1: Internal name replacement in WORK_PLAN.md
    print("=" * 60)
    print("Phase 1: Internal name → generic role name (WORK_PLAN.md)")
    print("=" * 60)
    wp_results, wp_names, wp_agents = scan_work_plan_files(check_only, verbose)
    if verbose:
        for rel, nh, ah in wp_results:
            print(f"  {rel}: {nh} name hits, {ah} agent hits")
    print(f"  Total: {len(wp_results)} files, {wp_names} name replacements, {wp_agents} agent_id replacements")
    print()

    # Phase 2: Agent ID cleanup across all docs/ .md
    print("=" * 60)
    print("Phase 2: Agent ID cleanup (all docs/ .md)")
    print("=" * 60)
    agent_results, agent_total = scan_all_docs_agent_ids(check_only, verbose)
    if verbose:
        for rel, n in agent_results:
            print(f"  {rel}: {n} hits")
    print(f"  Total: {len(agent_results)} files, {agent_total} agent_id replacements")
    print()

    # Phase 3: Archive markers
    print("=" * 60)
    print("Phase 3: Archive markers (R34-R44)")
    print("=" * 60)
    arch_results, arch_total = archive_old_rounds(check_only, verbose)
    if verbose:
        for rel in arch_results:
            print(f"  {rel}")
    print(f"  Total: {arch_total} files archived")
    print()

    # Summary
    print("=" * 60)
    mode = "CHECK (dry-run)" if check_only else "EXECUTE"
    print(f"Mode: {mode}")
    print(f"  WORK_PLAN.md files with changes: {len(wp_results)}")
    print(f"  Name replacements:              {wp_names}")
    print(f"  Agent ID replacements (WPs):    {wp_agents}")
    print(f"  Agent ID files (all docs/):     {len(agent_results)}")
    print(f"  Agent ID hits (all docs/):      {agent_total}")
    print(f"  Archived files (R34-R44):       {arch_total}")
    print("=" * 60)

    if check_only and any([wp_names, wp_agents, agent_total, arch_total]):
        print("\n⚠️  Issues found — run without --check to fix.")
        sys.exit(1)
    elif check_only:
        print("\n✅ All clean — no issues found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
