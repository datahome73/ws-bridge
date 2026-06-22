#!/bin/bash
# ws-bridge 快捷管理脚本
# 用法: ./ws-bridge.sh {start|stop|status|send|read|listen}

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$DIR/ws-bridge-client.js"
PID_FILE="$DIR/.ws-bridge-pid"
OUT_LOG="$DIR/ws-bridge-out.log"
ERR_LOG="$DIR/ws-bridge-err.log"
PIPE_FILE="$DIR/.ws-bridge-write"

case "${1:-status}" in
  start)
    # 检查是否已在运行
    if [ -f "$PID_FILE" ]; then
      OLD_PID=$(cat "$PID_FILE")
      if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running (pid $OLD_PID)"
        exit 0
      fi
    fi

    # 清理旧的管道文件
    [ -f "$PIPE_FILE" ] && rm -f "$PIPE_FILE"

    # 启动后台进程
    cd "$DIR"
    nohup node "$CLIENT" > "$OUT_LOG" 2> "$ERR_LOG" &
    PID=$!
    echo $PID > "$PID_FILE"
    echo "Started (pid $PID)"

    # 等待几秒检查启动
    sleep 2
    if kill -0 $PID 2>/dev/null; then
      echo "Process running"
      # 打印状态
      tail -3 "$OUT_LOG" 2>/dev/null || true
      # 检查配对码
      if grep -q "配对码" "$ERR_LOG" 2>/dev/null; then
        CODE=$(grep "配对码" "$ERR_LOG" | tail -1 | grep -oP '[A-Z0-9]{8}')
        echo ""
        echo "⚠️  需要管理员审批！配对码: $CODE"
      fi
      if grep -q "已接入" "$ERR_LOG" 2>/dev/null; then
        echo "✅ 已连接"
      fi
    else
      echo "Process failed to start!"
      cat "$ERR_LOG"
      exit 1
    fi
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 $PID 2>/dev/null; then
        kill $PID 2>/dev/null
        echo "Stopped (pid $PID)"
      else
        echo "Not running"
      fi
      rm -f "$PID_FILE"
    else
      echo "Not running"
    fi
    ;;

  status)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 $PID 2>/dev/null; then
        echo "● Running (pid $PID)"
        echo ""
        tail -5 "$OUT_LOG" 2>/dev/null || true
        echo "---"
        tail -3 "$ERR_LOG" 2>/dev/null || true
        if grep -q "已接入" "$ERR_LOG" 2>/dev/null; then
          echo ""
          echo "✅ 连接状态: 已认证"
        fi
        if grep -q "配对码" "$ERR_LOG" 2>/dev/null; then
          CODE=$(grep "配对码" "$ERR_LOG" | tail -1 | grep -oP '[A-Z0-9]{8}')
          echo ""
          echo "🔑 等待审批 (配对码: $CODE)"
        fi
      else
        echo "✕ Dead (pid file exists but process gone)"
        rm -f "$PID_FILE"
      fi
    else
      echo "✕ Not running"
    fi
    ;;

  send)
    if [ $# -lt 2 ]; then
      echo "Usage: $0 send <message>"
      exit 1
    fi
    shift
    MSG="$*"
    echo "SEND|$MSG" >> "$PIPE_FILE"
    echo "Sent: ${MSG:0:100}"
    ;;

  read)
    LINES="${2:-10}"
    if [ -f "$OUT_LOG" ]; then
      # 只输出 MSG 行
      grep "^\[MSG\]" "$OUT_LOG" | tail -n "$LINES" | while IFS='|' read -r prefix fromName fromAgent b64content; do
        if [ -n "$b64content" ]; then
          content=$(echo "$b64content" | base64 -d 2>/dev/null || echo "$b64content")
          echo "[$fromName] $content"
        fi
      done
    else
      echo "No log file yet"
    fi
    ;;

  info)
    # 显示汇总信息: 未读消息数 + 最新消息摘要
    if [ -f "$OUT_LOG" ]; then
      MSG_COUNT=$(grep -c "^\[MSG\]" "$OUT_LOG" 2>/dev/null || echo 0)
      echo "总消息数: $MSG_COUNT"
      echo ""
      echo "最新消息:"
      grep "^\[MSG\]" "$OUT_LOG" | tail -3 | while IFS='|' read -r prefix fromName fromAgent b64content; do
        if [ -n "$b64content" ]; then
          content=$(echo "$b64content" | base64 -d 2>/dev/null || echo "$b64content")
          echo "  [$fromName] ${content:0:120}"
        fi
      done
    fi
    tail -3 "$OUT_LOG" 2>/dev/null || true
    ;;

  clean)
    rm -f "$OUT_LOG" "$ERR_LOG" "$PIPE_FILE"
    echo "Logs cleaned"
    ;;

  log)
    tail -f "$OUT_LOG"
    ;;

  *)
    echo "Usage: $0 {start|stop|status|send <msg>|read [N]|info|log|clean}"
    exit 1
    ;;
esac
