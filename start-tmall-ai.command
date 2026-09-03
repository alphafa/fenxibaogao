#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT=17962
VERSION="9.2.5"
SERVER="$ROOT/server"
LOG="$SERVER/v9_1_0.log"

health_version() {
  curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("serverVersion",""))
except: print("")' 2>/dev/null
}

RUNNING="$(health_version || true)"
if [ "$RUNNING" = "$VERSION" ]; then
  open "http://127.0.0.1:$PORT/"
  exit 0
fi

if [ -n "$RUNNING" ]; then
  PID="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
  sleep 1
fi

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  osascript -e 'display alert "启动失败" message "端口 17962 被其他程序占用，请先关闭占用进程。" as critical' 2>/dev/null || true
  exit 1
fi

cd "$SERVER"
[ -f config.json ] || cp config.example.json config.json

osascript <<APPLESCRIPT
tell application "Terminal"
  do script "cd '$SERVER'; python3 server.py >> '$LOG' 2>&1"
end tell
APPLESCRIPT

for i in {1..40}; do
  V="$(health_version || true)"
  if [ "$V" = "$VERSION" ]; then
    open "http://127.0.0.1:$PORT/"
    exit 0
  fi
  sleep 0.3
done

open -a TextEdit "$LOG" 2>/dev/null || true
exit 1
