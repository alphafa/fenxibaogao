@echo off
setlocal
cd /d "%~dp0"
set "PORT=17962"
set "URL=http://127.0.0.1:%PORT%/"
set "EXE=%~dp0SansongAI.exe"
set "SERVER_DIR=%~dp0server"

if not exist "%EXE%" (
  echo SansongAI.exe was not found. Please extract the complete Windows package first.
  pause
  exit /b 1
)
if not exist "%SERVER_DIR%\config.json" if exist "%SERVER_DIR%\config.example.json" copy /y "%SERVER_DIR%\config.example.json" "%SERVER_DIR%\config.json" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%health'; if ($r.StatusCode -eq 200) { Start-Process '%URL%'; exit 0 } } catch {} ; exit 1" >nul 2>&1
if %errorlevel%==0 exit /b 0

start "SansongAI" /b "%EXE%"
for /l %%N in (1,1,40) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%URL%health'; if ($r.StatusCode -eq 200) { exit 0 } } catch {} ; exit 1" >nul 2>&1
  if not errorlevel 1 (
    start "" "%URL%"
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)
echo The local service did not start. Check that Windows Defender did not block SansongAI.exe.
pause
exit /b 1
