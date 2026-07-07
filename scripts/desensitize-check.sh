#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# scripts/desensitize-check.sh — R75 脱敏验证脚本
#
# 按 R75 scope 检查：
#   - WORK_PLAN.md 文件：检查内部角色名 + agent_id 残留
#   - 全部 docs/ .md 文件：检查 agent_id 残留
#   - R34-R44 WORK_PLAN.md：检查 🏁 归档标记
#
# Usage:
#   scripts/desensitize-check.sh               # 全量检查
#   scripts/desensitize-check.sh --quiet       # 仅返回 exit code
#   scripts/desensitize-check.sh --workplan    # 仅检查 WORK_PLAN.md
#
# Exit codes:
#   0 = 全部通过
#   1 = 有残留
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUIET=false
EXIT=0
SCOPE="${1:-all}"

if [[ "$SCOPE" == "--quiet" ]]; then
    QUIET=true
    SCOPE="all"
fi
if [[ "$SCOPE" == "--workplan" ]]; then
    SCOPE="workplan"
fi

msg() { if ! $QUIET; then echo "$@"; fi; }

# ── 1. WORK_PLAN.md 内部角色名检查 ─────────────────────────────────────
msg "═══ 检查 1/4：WORK_PLAN.md 内部角色名残留 ═══"

find "$REPO_ROOT/docs" -name 'WORK_PLAN.md' -print0 2>/dev/null | \
  xargs -0 grep -lnP '小谷|小爱|小开|爱泰|小周|泰虾|大宏' 2>/dev/null || true

hits=$(find "$REPO_ROOT/docs" -name 'WORK_PLAN.md' -exec grep -lP '小谷|小爱|小开|爱泰|小周|泰虾|大宏' {} \; 2>/dev/null)
if [[ -n "$hits" ]]; then
    msg "❌ WORK_PLAN.md 发现内部角色名残留:"
    echo "$hits"
    EXIT=1
else
    msg "✅ WORK_PLAN.md 无内部角色名残留"
fi

# ── 2. agent_id 检查（全部 docs/ .md） ────────────────────────────────
msg ""
msg "═══ 检查 2/4：agent_id 残留（全部 docs/ .md） ═══"

agent_hits=$(find "$REPO_ROOT/docs" -name '*.md' -exec grep -lnP 'ws_[0-9a-f]{12}' {} \; 2>/dev/null)
if [[ -n "$agent_hits" ]]; then
    msg "❌ 发现 agent_id 残留:"
    echo "$agent_hits"
    EXIT=1
else
    msg "✅ 无 agent_id 残留"
fi

# ── 3. R34-R44 🏁 归档标记 ────────────────────────────────────────────
msg ""
msg "═══ 检查 3/4：归档标记（R34-R44 WORK_PLAN.md） ═══"

missing=0
for num in $(seq 34 44); do
    wp="$REPO_ROOT/docs/R${num}/WORK_PLAN.md"
    if [[ -f "$wp" ]] && ! grep -q '🏁 已归档' "$wp" 2>/dev/null; then
        msg "❌ docs/R${num}/WORK_PLAN.md 缺少 🏁 归档标记"
        missing=$((missing + 1))
        EXIT=1
    fi
done
if [[ $missing -eq 0 ]]; then
    msg "✅ 全部 R34-R44 WORK_PLAN.md 已标记归档"
fi

# ── 4. docs/README.md 最新轮次 ───────────────────────────────────────
msg ""
msg "═══ 检查 4/4：docs/README.md 最新轮次 ═══"

if grep -q '最新轮次：\*\*R73\*\*' "$REPO_ROOT/docs/README.md" 2>/dev/null; then
    msg "✅ README.md 最新轮次为 R73"
else
    msg "❌ README.md 最新轮次不是 R73"
    EXIT=1
fi

# ── Final ──────────────────────────────────────────────────────────────
msg ""
if [[ $EXIT -eq 0 ]]; then
    msg "✅ 脱敏验证全部通过 — 无残留"
else
    msg "❌ 脱敏验证失败 — 发现残留，请修复后重新检查"
fi

exit $EXIT
