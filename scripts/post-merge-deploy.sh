#!/bin/bash
# After merging dev→main, trigger service redeploy
# Usage: cd ~/hermes-ws-bridge && bash scripts/post-merge-deploy.sh

set -e

echo "=== Post-merge deploy: ws-bridge ==="

# Step 1: Verify main has the latest
CURRENT=$(git rev-parse --short HEAD)
echo "Current HEAD: $CURRENT"

# Step 2: Trigger service redeploy
echo "Redeploying service..."
# Deploy: trigger your service's redeploy mechanism here.
# Examples: systemctl restart ws-bridge, docker compose up -d, or cloud provider CLI.
echo "Redeploy trigger: set DEPLOY_CMD env var or edit this script."

echo "Waiting 30s for deploy..."
sleep 30

# Step 3: Verify health
echo "Checking health..."
HEALTH_URL="${WS_BRIDGE_HEALTH_URL:-http://localhost:8765/api/health}"
curl -s "$HEALTH_URL" | python3 -m json.tool 2>/dev/null || echo "Health check failed (set WS_BRIDGE_HEALTH_URL)"

echo "=== Deploy complete ==="
