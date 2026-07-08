#!/usr/bin/env python3
"""Fix 3 review issues (B-1, W-1, S-1) and push to dev."""
import subprocess, sys, os, shutil

TMP = "/tmp/r76-fix"
if os.path.exists(TMP):
    shutil.rmtree(TMP)

token = ""
with open("/opt/data/.env") as f:
    for line in f:
        if line.startswith("GITHUB_TOKEN="):
            token = line.strip().split("=", 1)[1]
            break

# Clone
r = subprocess.run(
    ["git", "clone", "--depth=5", "-b", "dev",
     f"https://{token}@github.com/datahome73/ws-bridge.git", TMP],
    capture_output=True, text=True, timeout=30
)
print(r.stdout[-200:])

# Fix B-1: handle_api_inbox since parameter
path = os.path.join(TMP, "server/web_viewer.py")
with open(path) as f:
    orig = f.read()

# The problem:
#   since = request.query.get("since", None)
#   since = float(since) if since else None
# Need:
#   since = request.query.get("since", None)
#   if since:
#       try:
#           since = float(since)
#       except (ValueError, TypeError):
#           since = None

old_b1 = '    since = request.query.get("since", None)\n    since = float(since) if since else None\n'
new_b1 = '    since = request.query.get("since", None)\n    if since:\n        try:\n            since = float(since)\n        except (ValueError, TypeError):\n            since = None\n'
if old_b1 in orig:
    orig = orig.replace(old_b1, new_b1, 1)
    print("✅ B-1 fixed")
else:
    print("⚠️ B-1 not found, checking...")
    # Show surrounding code
    idx = orig.find("since = request.query.get")
    if idx >= 0:
        print(repr(orig[idx:idx+150]))

# Fix W-1: _time.time() -> time.time() (or just fallback to ws.created_at)
old_w1 = "start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else _time.time()"
new_w1 = "start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else time.time()"
if old_w1 in orig:
    orig = orig.replace(old_w1, new_w1, 1)
    print("✅ W-1 fixed")
else:
    print(f"⚠️ W-1 not found")

# Fix S-1: _save_archive_state add try/except
old_s1 = '    path.write_text(\n        json.dumps(state, ensure_ascii=False, indent=2),\n        encoding="utf-8",\n    )'
new_s1 = '    try:\n        path.write_text(\n            json.dumps(state, ensure_ascii=False, indent=2),\n            encoding="utf-8",\n        )\n    except OSError as exc:\n        logger.warning("R76: Failed to save archive state: %s", exc)'
if old_s1 in orig:
    orig = orig.replace(old_s1, new_s1, 1)
    print("✅ S-1 fixed")
else:
    print(f"⚠️ S-1 not found")

with open(path, "w") as f:
    f.write(orig)
print("✅ web_viewer.py written")

# Commit & push
os.chdir(TMP)
r = subprocess.run(["git", "add", "server/web_viewer.py"], capture_output=True, text=True, timeout=10)
r = subprocess.run(
    ["git", "-c", "user.name=需求分析师", "-c", "user.email=datahome73@gmail.com",
     "commit", "-m", "fix(R76): 修复审查发现 B-1/W-1/S-1 — since 参数安全 + 归档 IO 保护"],
    capture_output=True, text=True, timeout=10
)
print(r.stdout[-200:])

r = subprocess.run(
    ["git", "push", "origin", "dev"],
    capture_output=True, text=True, timeout=30
)
print(r.stdout[-200:])
print(r.stderr[-200:])
print("=== DONE ===")
