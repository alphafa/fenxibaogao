#!/bin/bash
PORT=17962
V=$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("serverVersion",""))
except: print("")' 2>/dev/null || true)
if [ -n "$V" ]; then
  PID="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
fi
osascript -e 'display notification "本地服务已停止" with title "三笙电商商品分析"' 2>/dev/null || true
