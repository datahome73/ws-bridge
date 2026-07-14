"""
R109 Step 6 — 合并部署执行脚本
小爱在生产机运行: python3 deploy_r109_step6.py
"""
import subprocess, sys, os

WORK_DIR = "/opt/data/ws-bridge"

def run(cmd, cwd=WORK_DIR, check=True):
    print(f"$ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0 and check:
        print(f"❌ 失败: {r.stderr.strip()}")
        sys.exit(1)
    if r.stdout.strip():
        print(r.stdout.strip()[:200])
    return r

print("=" * 50)
print("R109 Step 6 — 合并部署")
print("=" * 50)

# 1. 合并 dev → main
run("git checkout main")
run("git pull origin main")
run("git merge dev --no-edit")
run("git push origin main")
print("✅ PR: dev → main 合并完成")

# 2. 更新 TODO.md
# (小爱你手动或按惯例处理)

# 3. 重建镜像 & 重启
run("docker build -t ws-bridge:r109 .")
# 如果 docker-compose 管理
if os.path.exists(os.path.join(WORK_DIR, "docker-compose.yml")):
    run("docker compose up -d --force-recreate")
else:
    # 停旧容器重启
    run("docker stop ws-bridge 2>/dev/null; docker rm ws-bridge 2>/dev/null", check=False)
    run("docker run -d --name ws-bridge --restart unless-stopped "
        "-p 8765:8765 -p 8766:8766 "
        "-v /opt/data:/opt/data "
        "ws-bridge:r109")

print("\n✅ R109 Step 6 部署完成")
print("⚠️ 请验证: WSS 8765 🟢, Web 8766 🟢")
