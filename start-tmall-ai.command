#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT=17962
VERSION="9.3.0"
REFERENCE_ROLE_VERSION="20260911-reference-role-fix4"
SERVER="$ROOT/server"
LOG="$SERVER/v9_1_0.log"

health_identity() {
  curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null | python3 -c 'import sys,json
try:
 d=json.load(sys.stdin); print(d.get("serverVersion","")+"|"+d.get("configPath","")+"|"+d.get("referenceRoleVersion",""))
except: print("")' 2>/dev/null
}

EXPECTED="$VERSION|$SERVER/config.json|$REFERENCE_ROLE_VERSION"
RUNNING="$(health_identity || true)"
if [ "$RUNNING" = "$EXPECTED" ]; then
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
mkdir -p "$SERVER"
if [ ! -f config.json ] && [ -f config.example.json ]; then cp config.example.json config.json; fi

osascript <<APPLESCRIPT
tell application "Terminal"
  do script "cd '$SERVER'; python3 server.py >> '$LOG' 2>&1"
end tell
APPLESCRIPT

for i in {1..40}; do
  IDENTITY="$(health_identity || true)"
  if [ "$IDENTITY" = "$EXPECTED" ]; then
    open "http://127.0.0.1:$PORT/"
    exit 0
  fi
  sleep 0.3
done

open -a TextEdit "$LOG" 2>/dev/null || true
exit 1
