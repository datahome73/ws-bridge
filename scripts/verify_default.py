"""
R80: 全局默认验证脚本 — commit 存在性检查。

用法：python3 scripts/verify_default.py <output_ref>
exit=0: commit 存在
exit=1: commit 不存在
exit=0（无 output_ref 时跳过）
"""

import sys
import subprocess

output_ref = sys.argv[1] if len(sys.argv) > 1 else ""
if not output_ref:
    print("⏭️ 无 output_ref，跳过")
    sys.exit(0)

result = subprocess.run(
    ["git", "log", "--oneline", "-1", output_ref],
    capture_output=True, text=True,
)

if result.returncode != 0:
    print(f"❌ Commit {output_ref} 不存在于本地仓库")
    sys.exit(1)

print(f"✅ Commit {output_ref} 本地存在")
sys.exit(0)
